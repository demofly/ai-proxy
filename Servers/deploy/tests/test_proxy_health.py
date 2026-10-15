"""The recovery circuit must distinguish healthy/local failure and honor cooldown."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

import jinja2


@unittest.skipUnless(os.name == 'posix', 'requires bash/flock')
class HealthTests(unittest.TestCase):
    def test_consecutive_failures_cooldown_and_recovery(self):
        source = (Path(__file__).resolve().parents[1]/'templates/aiproxy-health.sh.j2').read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curl = root/'curl'
            curl.write_text('#!/bin/sh\nif [ -f "'+str(root/'healthy')+'" ]; then echo "Squid Object Cache"; exit 0; fi\nexit 7\n')
            curl.chmod(0o755)
            systemctl = root/'systemctl'
            systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "'+str(root/'restarts')+'"\n')
            systemctl.chmod(0o755)
            script = root/'check'
            rendered = jinja2.Template(source).render(ansible_managed='test', keepalived_restart_cooldown=30)
            rendered = rendered.replace('/run/aiproxy-squid-health', str(root/'state'))
            rendered = rendered.replace('/usr/bin/curl', str(curl)).replace('/usr/bin/systemctl', str(systemctl))
            script.write_text(rendered)
            def check(expected):
                result = subprocess.run(['bash', str(script)], capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
            check(1)
            check(1)
            self.assertFalse((root/'restarts').exists())
            check(1)
            check(1)
            self.assertEqual((root/'restarts').read_text().splitlines(), ['--no-block restart squid'])
            (root/'healthy').touch()
            check(0)
            self.assertEqual((root/'state.failures').read_text().strip(), '0')
            (root/'healthy').unlink()
            check(1)
            check(1)
            self.assertEqual(len((root/'restarts').read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
