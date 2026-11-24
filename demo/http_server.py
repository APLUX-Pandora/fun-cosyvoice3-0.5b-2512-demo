"""Own WSGI responses through transport errors as well as normal completion."""
import ssl

from werkzeug.serving import WSGIRequestHandler

_RESPONSE_OWNER = "pandora.response_owner"


class ResponseOwner:
    """Close the application iterable once, including when socket cleanup fails."""

    def __init__(self, response):
        self.response = response
        self.iterator = iter(response)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        if self.closed:
            return
        self.closed = True
        close = getattr(self.response, "close", None)
        if close is not None:
            close()


class ClosingApplication:
    """Keep the response reachable by the request handler until it is closed."""

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        response = ResponseOwner(self.application(environ, start_response))
        environ[_RESPONSE_OWNER] = response
        return response


class _DisconnectDrain:
    """Stop draining a dead connection without changing application body reads."""

    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, *args):
        try:
            return self.stream.read(*args)
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            return b""
        except ssl.SSLError as exc:
            if isinstance(exc, (ssl.SSLEOFError, ssl.SSLZeroReturnError)) or getattr(
                exc, "reason", None
            ) == "UNEXPECTED_EOF_WHILE_READING":
                return b""
            raise


class RequestHandler(WSGIRequestHandler):
    def setup(self):
        super().setup()
        # Bound stalled request bodies and blocked writes so shutdown can join handlers.
        self.connection.settimeout(15)

    def make_environ(self):
        environ = super().make_environ()
        # wsgi.input already owns the original reader (including chunked decoding).
        # Only Werkzeug's post-response drain uses this EOF-tolerant view, allowing
        # its selector to close even if the peer omitted TLS close_notify.
        self.rfile = _DisconnectDrain(self.rfile)
        return environ

    def run_wsgi(self):
        stream = self.rfile
        try:
            return super().run_wsgi()
        finally:
            self.rfile = stream
            # TLS EOF or request-body draining can raise before Werkzeug closes the
            # iterable. Always finish the generator that owns the synthesis lock.
            response = getattr(self, "environ", {}).pop(_RESPONSE_OWNER, None)
            if response is not None:
                response.close()
