# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test cases for dhcp.config"""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

from os import (
    makedirs,
    path,
    )
from textwrap import dedent

from fixtures import EnvironmentVariableFixture
from maastesting.factory import factory
from provisioningserver.boot import BootMethodRegistry
from provisioningserver.dhcp import config
from provisioningserver.testing.testcase import PservTestCase
import tempita
from testtools.matchers import (
    Contains,
    MatchesRegex,
    )

# Simple test version of the DHCP template.  Contains parameter
# substitutions, but none that aren't also in the real template.
sample_template = dedent("""\
    {{omapi_key}}
    {{for dhcp_subnet in dhcp_subnets}}
        {{dhcp_subnet['subnet']}}
        {{dhcp_subnet['interface']}}
        {{dhcp_subnet['subnet_mask']}}
        {{dhcp_subnet['broadcast_ip']}}
        {{dhcp_subnet['dns_servers']}}
        {{dhcp_subnet['domain_name']}}
        {{dhcp_subnet['router_ip']}}
        {{dhcp_subnet['ip_range_low']}}
        {{dhcp_subnet['ip_range_high']}}
    {{endfor}}
""")


def make_sample_params():
    """Produce a dict of sample parameters.

    The sample provides all parameters used by the DHCP template.
    """
    return dict(
        omapi_key="random",
        dhcp_subnets=[dict(
            subnet="10.0.0.0",
            interface="eth0",
            subnet_mask="255.0.0.0",
            broadcast_ip="10.255.255.255",
            dns_servers="10.1.0.1 10.1.0.2",
            ntp_server="8.8.8.8",
            domain_name="example.com",
            router_ip="10.0.0.2",
            ip_range_low="10.0.0.3",
            ip_range_high="10.0.0.254",
            )]
        )


class TestDHCPConfig(PservTestCase):

    def patch_template(self, template_content=sample_template):
        """Patch the DHCP config template with the given contents.

        Returns a `tempita.Template` of the given template, so that a test
        can make its own substitutions and compare to those made by the
        code being tested.
        """
        fake_etc_maas = self.make_dir()
        self.useFixture(EnvironmentVariableFixture(
            'MAAS_CONFIG_DIR', fake_etc_maas))
        template_dir = path.join(fake_etc_maas, 'templates', 'dhcp')
        makedirs(template_dir)
        template = factory.make_file(
            template_dir, 'dhcpd.conf.template', contents=template_content)
        return tempita.Template(template_content, name=template)

    def test_uses_branch_template_by_default(self):
        # Since the branch comes with a dhcp template in etc/maas, we can
        # instantiate that template without any hackery.
        self.assertIsNotNone(config.get_config(**make_sample_params()))

    def test_param_substitution(self):
        template = self.patch_template()
        params = make_sample_params()
        self.assertEqual(
            template.substitute(params),
            config.get_config(**params))

    def test_get_config_with_too_few_parameters(self):
        template = self.patch_template()
        params = make_sample_params()
        del params['dhcp_subnets'][0]['subnet']

        e = self.assertRaises(
            config.DHCPConfigError, config.get_config, **params)

        self.assertThat(
            unicode(e), MatchesRegex(
                "subnet at line \d+ column \d+ "
                "in file %s" % template.name))

    def test_compose_conditional_bootloader(self):
        output = config.compose_conditional_bootloader()
        for method in BootMethodRegistry.get_items().values():
            self.assertThat(output, Contains(method.arch_octet))
            self.assertThat(output, Contains(method.bootloader_path))

    def test_config_contains_compose_conditional_bootloader(self):
        params = make_sample_params()
        bootloader = config.compose_conditional_bootloader()
        self.assertThat(config.get_config(**params), Contains(bootloader))

    def test_renders_without_ntp_servers_set(self):
        params = make_sample_params()
        del params['dhcp_subnets'][0]['ntp_server']
        template = self.patch_template()
        rendered = template.substitute(params)
        self.assertEqual(rendered, config.get_config(**params))
        self.assertNotIn("ntp-servers", rendered)
