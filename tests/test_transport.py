
# Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import itertools

import fixtures
import mox
from oslo.config import cfg
from stevedore import driver
import testscenarios

from oslo import messaging
from oslo.messaging import transport
from tests import utils as test_utils

load_tests = testscenarios.load_tests_apply_scenarios


class _FakeDriver(object):

    def __init__(self, conf):
        self.conf = conf

    def send(self, *args, **kwargs):
        pass

    def send_notification(self, *args, **kwargs):
        pass

    def listen(self, target):
        pass


class _FakeManager(object):

    def __init__(self, driver):
        self.driver = driver


class GetTransportTestCase(test_utils.BaseTestCase):

    scenarios = [
        ('all_none',
         dict(url=None, transport_url=None, rpc_backend=None,
              control_exchange=None,
              expect=dict(backend=None,
                          exchange=None,
                          url=None))),
        ('rpc_backend',
         dict(url=None, transport_url=None, rpc_backend='testbackend',
              control_exchange=None,
              expect=dict(backend='testbackend',
                          exchange=None,
                          url=None))),
        ('control_exchange',
         dict(url=None, transport_url=None, rpc_backend=None,
              control_exchange='testexchange',
              expect=dict(backend=None,
                          exchange='testexchange',
                          url=None))),
        ('transport_url',
         dict(url=None, transport_url='testtransport:', rpc_backend=None,
              control_exchange=None,
              expect=dict(backend='testtransport',
                          exchange=None,
                          url='testtransport:'))),
        ('url_param',
         dict(url='testtransport:', transport_url=None, rpc_backend=None,
              control_exchange=None,
              expect=dict(backend='testtransport',
                          exchange=None,
                          url='testtransport:'))),
    ]

    def setUp(self):
        super(GetTransportTestCase, self).setUp(conf=cfg.ConfigOpts())
        self.conf.register_opts(transport._transport_opts)

    def test_get_transport(self):
        self.config(rpc_backend=self.rpc_backend,
                    control_exchange=self.control_exchange,
                    transport_url=self.transport_url)

        self.mox.StubOutWithMock(driver, 'DriverManager')

        invoke_args = [self.conf]
        invoke_kwds = dict(default_exchange=self.expect['exchange'])
        if self.expect['url']:
            invoke_kwds['url'] = self.expect['url']

        drvr = _FakeDriver(self.conf)
        driver.DriverManager('oslo.messaging.drivers',
                             self.expect['backend'],
                             invoke_on_load=True,
                             invoke_args=invoke_args,
                             invoke_kwds=invoke_kwds).\
            AndReturn(_FakeManager(drvr))

        self.mox.ReplayAll()

        transport = messaging.get_transport(self.conf, url=self.url)

        self.assertIsNotNone(transport)
        self.assertIs(transport.conf, self.conf)
        self.assertIs(transport._driver, drvr)


class GetTransportSadPathTestCase(test_utils.BaseTestCase):

    scenarios = [
        ('invalid_transport_url',
         dict(url=None, transport_url='invalid', rpc_backend=None,
              ex=dict(cls=messaging.InvalidTransportURL,
                      msg_contains='No scheme specified',
                      url='invalid'))),
        ('invalid_url_param',
         dict(url='invalid', transport_url=None, rpc_backend=None,
              ex=dict(cls=messaging.InvalidTransportURL,
                      msg_contains='No scheme specified',
                      url='invalid'))),
        ('driver_load_failure',
         dict(url=None, transport_url=None, rpc_backend='testbackend',
              ex=dict(cls=messaging.DriverLoadFailure,
                      msg_contains='Failed to load',
                      driver='testbackend'))),
    ]

    def setUp(self):
        super(GetTransportSadPathTestCase, self).setUp(conf=cfg.ConfigOpts())
        self.conf.register_opts(transport._transport_opts)

    def test_get_transport_sad(self):
        self.config(rpc_backend=self.rpc_backend,
                    transport_url=self.transport_url)

        if self.rpc_backend:
            self.mox.StubOutWithMock(driver, 'DriverManager')

            invoke_args = [self.conf]
            invoke_kwds = dict(default_exchange='openstack')

            driver.DriverManager('oslo.messaging.drivers',
                                 self.rpc_backend,
                                 invoke_on_load=True,
                                 invoke_args=invoke_args,
                                 invoke_kwds=invoke_kwds).\
                AndRaise(RuntimeError())

            self.mox.ReplayAll()

        try:
            messaging.get_transport(self.conf, url=self.url)
            self.assertFalse(True)
        except Exception as ex:
            ex_cls = self.ex.pop('cls')
            ex_msg_contains = self.ex.pop('msg_contains')

            self.assertIsInstance(ex, messaging.MessagingException)
            self.assertIsInstance(ex, ex_cls)
            self.assertTrue(hasattr(ex, 'msg'))
            self.assertIn(ex_msg_contains, ex.msg)

            for k, v in self.ex.items():
                self.assertTrue(hasattr(ex, k))
                self.assertEqual(getattr(ex, k), v)


# FIXME(markmc): this could be used elsewhere
class _SetDefaultsFixture(fixtures.Fixture):

    def __init__(self, set_defaults, opts, *names):
        super(_SetDefaultsFixture, self).__init__()
        self.set_defaults = set_defaults
        self.opts = opts
        self.names = names

    def setUp(self):
        super(_SetDefaultsFixture, self).setUp()

        # FIXME(markmc): this comes from Id5c1f3ba
        def first(seq, default=None, key=None):
            if key is None:
                key = bool
            return next(itertools.ifilter(key, seq), default)

        def default(opts, name):
            return first(opts, key=lambda o: o.name == name).default

        orig_defaults = {}
        for n in self.names:
            orig_defaults[n] = default(self.opts, n)

        def restore_defaults():
            self.set_defaults(**orig_defaults)

        self.addCleanup(restore_defaults)


class TestSetDefaults(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSetDefaults, self).setUp(conf=cfg.ConfigOpts())
        self.useFixture(_SetDefaultsFixture(messaging.set_transport_defaults,
                                            transport._transport_opts,
                                            'control_exchange'))

    def test_set_default_control_exchange(self):
        messaging.set_transport_defaults(control_exchange='foo')

        self.mox.StubOutWithMock(driver, 'DriverManager')
        invoke_kwds = mox.ContainsKeyValue('default_exchange', 'foo')
        driver.DriverManager(mox.IgnoreArg(),
                             mox.IgnoreArg(),
                             invoke_on_load=mox.IgnoreArg(),
                             invoke_args=mox.IgnoreArg(),
                             invoke_kwds=invoke_kwds).\
            AndReturn(_FakeManager(_FakeDriver(self.conf)))
        self.mox.ReplayAll()

        messaging.get_transport(self.conf)


class TestTransportMethodArgs(test_utils.BaseTestCase):

    _target = messaging.Target(topic='topic', server='server')

    def test_send_defaults(self):
        t = transport.Transport(_FakeDriver(cfg.CONF))

        self.mox.StubOutWithMock(t._driver, 'send')
        t._driver.send(self._target, 'ctxt', 'message',
                       wait_for_reply=None,
                       timeout=None)
        self.mox.ReplayAll()

        t._send(self._target, 'ctxt', 'message')

    def test_send_all_args(self):
        t = transport.Transport(_FakeDriver(cfg.CONF))

        self.mox.StubOutWithMock(t._driver, 'send')
        t._driver.send(self._target, 'ctxt', 'message',
                       wait_for_reply='wait_for_reply',
                       timeout='timeout')
        self.mox.ReplayAll()

        t._send(self._target, 'ctxt', 'message',
                wait_for_reply='wait_for_reply',
                timeout='timeout')

    def test_send_notification(self):
        t = transport.Transport(_FakeDriver(cfg.CONF))

        self.mox.StubOutWithMock(t._driver, 'send')
        t._driver.send(self._target, 'ctxt', 'message', 1.0)
        self.mox.ReplayAll()

        t._send_notification(self._target, 'ctxt', 'message', version=1.0)

    def test_listen(self):
        t = transport.Transport(_FakeDriver(cfg.CONF))

        self.mox.StubOutWithMock(t._driver, 'listen')
        t._driver.listen(self._target)
        self.mox.ReplayAll()

        t._listen(self._target)
