from six.moves import cStringIO as StringIO
from mock import Mock

from netlib import http
from netlib import tcp
from netlib.exceptions import NetlibException
from netlib.http import http1, http2

from pathod import pathoc, language
from netlib.tutils import raises
import tutils


def test_response():
    r = http.Response("HTTP/1.1", 200, "Message", {}, None, None)
    assert repr(r)


class PathocTestDaemon(tutils.DaemonTests):
    def tval(self, requests, timeout=None, showssl=False, **kwargs):
        s = StringIO()
        c = pathoc.Pathoc(
            ("127.0.0.1", self.d.port),
            ssl=self.ssl,
            fp=s,
            **kwargs
        )
        with c.connect(showssl=showssl, fp=s):
            if timeout:
                c.settimeout(timeout)
            for i in requests:
                r = language.parse_pathoc(i).next()
                if kwargs.get("explain"):
                    r = r.freeze(language.Settings())
                try:
                    c.request(r)
                except NetlibException:
                    pass
        self.d.wait_for_silence()
        return s.getvalue()


class TestDaemonSSL(PathocTestDaemon):
    ssl = True
    ssloptions = dict(
        request_client_cert=True,
        sans=["test1.com", "test2.com"],
        alpn_select=b'h2',
    )

    def test_sni(self):
        self.tval(
            ["get:/p/200"],
            sni="foobar.com"
        )
        log = self.d.log()
        assert log[0]["request"]["sni"] == "foobar.com"

    def test_showssl(self):
        assert "certificate chain" in self.tval(["get:/p/200"], showssl=True)

    def test_clientcert(self):
        self.tval(
            ["get:/p/200"],
            clientcert=tutils.test_data.path("data/clientcert/client.pem"),
        )
        log = self.d.log()
        assert log[0]["request"]["clientcert"]["keyinfo"]

    def test_http2_without_ssl(self):
        fp = StringIO()
        c = pathoc.Pathoc(
            ("127.0.0.1", self.d.port),
            use_http2=True,
            ssl=False,
            fp = fp
        )
        tutils.raises(NotImplementedError, c.connect)


class TestDaemon(PathocTestDaemon):
    ssl = False

    def test_ssl_error(self):
        c = pathoc.Pathoc(("127.0.0.1", self.d.port), ssl=True, fp=None)
        tutils.raises("ssl handshake", c.connect)

    def test_showssl(self):
        assert "certificate chain" not in self.tval(
            ["get:/p/200"],
            showssl=True)

    def test_ignorecodes(self):
        assert "200" in self.tval(["get:'/p/200:b@1'"])
        assert "200" in self.tval(["get:'/p/200:b@1'"])
        assert "200" in self.tval(["get:'/p/200:b@1'"])
        assert "200" not in self.tval(["get:'/p/200:b@1'"], ignorecodes=[200])
        assert "200" not in self.tval(
            ["get:'/p/200:b@1'"],
            ignorecodes=[
                200,
                201])
        assert "202" in self.tval(["get:'/p/202:b@1'"], ignorecodes=[200, 201])

    def _test_timeout(self):
        assert "Timeout" in self.tval(["get:'/p/200:p0,100'"], timeout=0.01)
        assert "HTTP" in self.tval(
            ["get:'/p/200:p5,100'"],
            showresp=True,
            timeout=1
        )
        assert "HTTP" not in self.tval(
            ["get:'/p/200:p3,100'"],
            showresp=True,
            timeout=1,
            ignoretimeout=True
        )

    def test_showresp(self):
        reqs = ["get:/p/200:da", "get:/p/200:da"]
        assert self.tval(reqs).count("200 OK") == 2
        assert self.tval(reqs, showresp=True).count("HTTP/1.1 200 OK") == 2
        assert self.tval(
            reqs, showresp=True, hexdump=True
        ).count("0000000000") == 2

    def test_showresp_httperr(self):
        v = self.tval(["get:'/p/200:d20'"], showresp=True, showsummary=True)
        assert "Invalid header" in v
        assert "HTTP/" in v

    def test_explain(self):
        reqs = ["get:/p/200:b@100"]
        assert "b@100" not in self.tval(reqs, explain=True)

    def test_showreq(self):
        reqs = ["get:/p/200:da", "get:/p/200:da"]
        assert self.tval(reqs, showreq=True).count("GET /p/200") == 2
        assert self.tval(
            reqs, showreq=True, hexdump=True
        ).count("0000000000") == 2

    def test_conn_err(self):
        assert "Invalid server response" in self.tval(["get:'/p/200:d2'"])

    def test_websocket_shutdown(self):
        self.tval(["ws:/"])

    def test_wait_finish(self):
        c = pathoc.Pathoc(
            ("127.0.0.1", self.d.port),
            fp=None,
            ws_read_limit=1
        )
        with c.connect():
            c.request("ws:/")
            c.request("wf:f'wf'")
            # This should read a frame and close the websocket reader
            assert len([i for i in c.wait(timeout=5, finish=False)]) == 1
            assert not [i for i in c.wait(timeout=0)]

    def test_connect_fail(self):
        to = ("foobar", 80)
        c = pathoc.Pathoc(("127.0.0.1", self.d.port), fp=None)
        c.rfile, c.wfile = StringIO(), StringIO()
        with raises("connect failed"):
            c.http_connect(to)
        c.rfile = StringIO(
            "HTTP/1.1 500 OK\r\n"
        )
        with raises("connect failed"):
            c.http_connect(to)
        c.rfile = StringIO(
            "HTTP/1.1 200 OK\r\n"
        )
        c.http_connect(to)

    def test_socks_connect(self):
        to = ("foobar", 80)
        c = pathoc.Pathoc(("127.0.0.1", self.d.port), fp=None)
        c.rfile, c.wfile = tutils.treader(""), StringIO()
        tutils.raises(pathoc.PathocError, c.socks_connect, to)

        c.rfile = tutils.treader(
            "\x05\xEE"
        )
        tutils.raises("SOCKS without authentication", c.socks_connect, ("example.com", 0xDEAD))

        c.rfile = tutils.treader(
            "\x05\x00" +
            "\x05\xEE\x00\x03\x0bexample.com\xDE\xAD"
        )
        tutils.raises("SOCKS server error", c.socks_connect, ("example.com", 0xDEAD))

        c.rfile = tutils.treader(
            "\x05\x00" +
            "\x05\x00\x00\x03\x0bexample.com\xDE\xAD"
        )
        c.socks_connect(("example.com", 0xDEAD))


class TestDaemonHTTP2(PathocTestDaemon):
    ssl = True
    explain = False

    if tcp.HAS_ALPN:

        def test_http2(self):
            c = pathoc.Pathoc(
                ("127.0.0.1", self.d.port),
                fp=None,
                ssl=True,
                use_http2=True,
            )
            assert isinstance(c.protocol, http2.HTTP2Protocol)

            c = pathoc.Pathoc(
                ("127.0.0.1", self.d.port),
            )
            assert c.protocol == http1

        def test_http2_alpn(self):
            c = pathoc.Pathoc(
                ("127.0.0.1", self.d.port),
                fp=None,
                ssl=True,
                use_http2=True,
                http2_skip_connection_preface=True,
            )

            tmp_convert_to_ssl = c.convert_to_ssl
            c.convert_to_ssl = Mock()
            c.convert_to_ssl.side_effect = tmp_convert_to_ssl
            with c.connect():
                _, kwargs = c.convert_to_ssl.call_args
                assert set(kwargs['alpn_protos']) == set([b'http/1.1', b'h2'])

        def test_request(self):
            c = pathoc.Pathoc(
                ("127.0.0.1", self.d.port),
                fp=None,
                ssl=True,
                use_http2=True,
            )
            with c.connect():
                resp = c.request("get:/p/200")
            assert resp.status_code == 200
