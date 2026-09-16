# SPDX-License-Identifier: MIT
"""Pure policy/parser tests. All network/APT data below is explicitly synthetic."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build as bk
debian = bk.debian

POLICY = '''Package files:
 100 /var/lib/dpkg/status
     release a=now
 500 https://deb.debian.org/debian testing/main amd64 Packages
     release o=Debian,a=testing,n=forky,l=Debian,c=main,b=amd64
     origin deb.debian.org
 500 https://deb.debian.org/debian sid/main amd64 Packages
     release o=Debian,a=unstable,n=sid,l=Debian,c=main,b=amd64
     origin deb.debian.org
 999 https://example.invalid/forky forky/main amd64 Packages
     release o=Other,n=forky
'''
FORKY_INDEX = 'https://deb.debian.org/debian testing/main amd64 Packages'


class DebianPolicyTests(unittest.TestCase):
    def test_testing_alias_uses_release_codename_not_url(self):
        self.assertEqual(debian.forky_indexes(POLICY), {FORKY_INDEX})

    def test_new_testing_codename_is_not_forky(self):
        self.assertEqual(debian.forky_indexes(POLICY.replace('n=forky,l=Debian', 'n=duke,l=Debian')), set())

    def test_madison_excludes_sid_and_third_party(self):
        data = f'gcc | 16.1.0-1 | {FORKY_INDEX}\n'
        data += 'gcc | 99.0.0-1 | https://deb.debian.org/debian sid/main amd64 Packages\n'
        self.assertEqual(debian.madison_versions(data, debian.forky_indexes(POLICY)), ['16.1.0-1'])

    def test_dpkg_epoch_and_revision_comparison(self):
        self.assertTrue(debian.newer('1:1.0-1', '9.0-99'))
        self.assertTrue(debian.newer('1.0-2', '1.0-1'))
        self.assertFalse(debian.newer('1.0~rc1', '1.0'))

    def test_host_codename_enforced_even_when_version_id_absent(self):
        with patch.object(debian, 'host_release', return_value={'ID': 'debian', 'VERSION_CODENAME': 'forky'}):
            self.assertEqual(debian.require_forky()['VERSION_CODENAME'], 'forky')
        with patch.object(debian, 'host_release', return_value={'ID': 'debian', 'VERSION_CODENAME': 'trixie'}):
            with self.assertRaises(debian.DebianError):
                debian.require_forky(allow_override=False)

    def test_build_override_never_allows_wrong_suite_apt_install(self):
        with patch.object(debian, 'host_release', return_value={'ID': 'debian', 'VERSION_CODENAME': 'trixie'}):
            with patch.dict(os.environ, {'ALLOW_UNSUPPORTED_DEBIAN': '1'}):
                debian.require_forky()
                with self.assertRaises(debian.DebianError):
                    debian.require_forky(allow_override=False)

    def test_os_release_parsed_without_sourcing_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'os-release'
            path.write_text('ID=debian\nVERSION_CODENAME=forky\nPRETTY_NAME="Debian GNU/Linux forky/sid"\n')
            self.assertEqual(debian.host_release(path)['PRETTY_NAME'], 'Debian GNU/Linux forky/sid')

    def test_invalid_package_list_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'packages').mkdir()
            (root / 'packages/build.txt').write_text('--allow-unauthenticated\n')
            with self.assertRaises(debian.DebianError):
                debian.package_list(root, 'build')

    def _runner(self, *, installed='1.0-1', simulation=None):
        calls = []
        def run(argv, **kwargs):
            calls.append(list(argv))
            if argv[:2] == ['apt-cache', 'policy']:
                return POLICY
            if argv[:2] == ['apt-cache', 'madison']:
                return f'{argv[2]} | 1.1-1 | {FORKY_INDEX}\n{argv[2]} | 99-1 | https://deb.debian.org/debian sid/main amd64 Packages\n'
            if argv[:2] == ['apt-cache', 'show']:
                return ''
            if argv[0] == 'dpkg-query':
                return f'gcc\t{installed}\tinstalled\n'
            if argv == ['dpkg', '--print-architecture']:
                return 'amd64\n'
            if '--simulate' in argv:
                return simulation or 'Inst gcc [1.0-1] (1.1-1 Debian:testing [amd64])\n'
            raise AssertionError(f'Unexpected command: {argv}')
        return run, calls

    def test_plan_selects_newest_forky_version(self):
        run, _ = self._runner()
        with patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            plan = debian.dependency_plan(ROOT, 'build', run)
        self.assertEqual(plan['packages'][0]['version'], '1.1-1')

    def test_compiler_metapackages_resolve_current_implementation_recursively(self):
        basic, calls = self._runner()
        def run(argv, **kwargs):
            if argv[:2] == ['apt-cache', 'show']:
                package = argv[2].split('=', 1)[0]
                return {'gcc': 'Depends: gcc-99 (>= 1), cpp (= 1)\n',
                        'gcc-99': 'Depends: gcc-99-x86-64-linux-gnu (= 1), libc6 (>= 1)\n'}.get(package, '')
            return basic(argv, **kwargs)
        with patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            plan = debian.dependency_plan(ROOT, 'build', run)
        self.assertEqual({item['package'] for item in plan['packages']},
                         {'gcc', 'gcc-99', 'gcc-99-x86-64-linux-gnu', 'cpp'})
        self.assertEqual(plan['declared_packages'], ['gcc'])

    def test_apt_parsing_uses_c_locale_in_a_localized_shell(self):
        basic, _ = self._runner()
        def run(argv, **kwargs):
            self.assertEqual(kwargs['env']['LC_ALL'], 'C')
            self.assertEqual(kwargs['env']['LANG'], 'C')
            return basic(argv, **kwargs)
        with patch.dict(os.environ, {'LANG': 'sv_SE.UTF-8', 'LC_ALL': 'sv_SE.UTF-8'}), \
             patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            debian.dependency_plan(ROOT, 'build', run)

    def test_plan_refuses_implicit_downgrade(self):
        run, _ = self._runner(installed='99-1')
        with patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            with self.assertRaises(debian.DebianError):
                debian.dependency_plan(ROOT, 'build', run)

    def test_plan_only_never_runs_install_or_update(self):
        run, calls = self._runner()
        with patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            debian.install_dependencies(ROOT, 'build', run, lambda *a: None, plan_only=True)
        apt = [args for args in calls if args[0] == 'apt-get']
        self.assertEqual(len(apt), 1)
        self.assertIn('--simulate', apt[0])
        self.assertIn('--no-remove', apt[0])

    def test_transitive_sid_dependency_rejected(self):
        run, _ = self._runner(simulation='Inst alien-lib (99-1 Debian:unstable [amd64])\n')
        with patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            with self.assertRaises(debian.DebianError):
                debian.install_dependencies(ROOT, 'build', run, lambda *a: None, plan_only=True)

    def test_removal_plan_rejected(self):
        run, _ = self._runner(simulation='Remv unrelated-package [1.0]\n')
        with patch.object(debian, 'require_forky'), patch.object(debian, 'package_list', return_value=['gcc']):
            with self.assertRaises(debian.DebianError):
                debian.install_dependencies(ROOT, 'build', run, lambda *a: None, plan_only=True)


if __name__ == "__main__":
    unittest.main()
