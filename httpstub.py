#!/usr/bin/env python
import sys, re, cgi, os, tempfile, time, pickle, BaseHTTPServer

class Record:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)
    set = __init__

class HTTPStubRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    MENU = [{'url':'/', 'title':'Home', 'desc':''},
            {'url':'/add', 'title':'Add new response', 'desc':'Configure a response that will be returned to clients'},
            {'url':'/visit', 'title':'Make a request', 'desc':'Receive the pre-configured response (point apps at the URL of this link)'}]
    SEQUENTIAL, STICKY, REACTIVE = range(3)
    MODES = {'Sequential': SEQUENTIAL, 'Sticky': STICKY, 'Reactive': REACTIVE}
    STORAGE_VERSION = 2

    def do_POST(self): self._handle('POST')

    def do_GET(self): self._handle('GET')

    def _handle(self, method):
        self.method = method
        page_name = re.match('^/+(\w*)([\?/].*)?$', self.path).group(1)
        try: handler = getattr(self, "handle_%s" % page_name)
        except AttributeError: self.respond(404, 'Page not found: %s' % page_name)
        else:
            self.open_storage()
            try: self.respond(*handler())
            finally: self.close_storage()

    def with_open_file(self, filename, mode, func):
        f = open(filename, mode)
        try: return func(f)
        finally: f.close()

    def open_storage(self):
        try:
            self.storage = self.with_open_file(self.storage_filename, 'rb', pickle.load)
            if self.storage.version < self.STORAGE_VERSION:
                print "Storage formats have changed: discarding old requests and responses; sorry."
                raise IOError, "old file format"
        except IOError:
            self.storage = Record(version=self.STORAGE_VERSION, requests=[], responses=[], next_request=0, mode=self.SEQUENTIAL)

    def close_storage(self):
        self.with_open_file(self.storage_filename, 'wb', lambda f: pickle.dump(self.storage, f))

    def path_arg(self):
        return int(self.path.split('/')[2])
                
    def handle_(self):
        body_lines = ["<h3>Menu</h3>"] + \
                     ['<li><a href="%(url)s">%(title)s</a>: %(desc)s\n' % entry for entry in self.MENU[1:]] + \
                     ["<h3>Configured responses</h3>"]
        if self.storage.responses:
            body_lines.append('<a href="/clear_responses">Clear preset responses</a><table border=0>')
            counter = 0
            for response in self.storage.responses:
                if self.storage.mode != self.REACTIVE and counter == self.storage.next_request:
                    position_indicator = '<strong>&gt;&gt;&gt;</strong> '
                    if self.storage.mode == self.STICKY: position_indicator += '(sticky)'
                else:
                    position_indicator = ''
                body_lines.append('<tr><td>%d</td><td>%s</td><td><a href="/visit_raw/%d">Code %s, Content-Type %s</a></td><td>' % (counter + 1, position_indicator, counter, response.status, response.content_type))
                body_lines.append('[<a href="/edit/%d">Edit</a>] ' % counter)
                body_lines.append('[<a href="/remove_response/%d">Delete</a>] ' % counter)
                if self.storage.mode != self.REACTIVE:
                    body_lines.append('[<a href="/set_next_request/%d">Set as next request</a>] ' % counter)
                body_lines.append("</td></tr>")
                counter += 1
            body_lines.append('</table>')
        body_lines.append("<h3>Received requests</h3>")
        if self.storage.requests:
            body_lines.append('<a href="/clear_requests">Clear received requests</a><ol>')
            counter = 0
            for req in self.storage.requests:
                body_lines.append('<li><a href="/show/%d">%s %s at %s</a>' % (counter, req.method, req.path, time.ctime(req.timestamp)))
                counter += 1
            body_lines.append('</ol>')
        return (200, self.page('HTTP Stub', "".join(body_lines)))

    def read_request_body(self):
        if self.method == 'GET': return ''
        return self.rfile.read(int(self.headers.get('content-length', -1)))

    def handle_remove_response(self):
        try:
            index = self.path_arg()
            resp = self.storage.responses[index]
        except IndexError:
            return (500, self.page('Error', 'NO SUCH REQUEST: %s' % sys.exc_info()[1]))
        del self.storage.responses[index]
        if index == self.storage.next_request:
            self.storage.next_request = 0
        return (200, self.message_page("Request %s deleted" % (index + 1)))

    def handle_set_next_request(self):
        try:
            index = self.path_arg()
            req = self.storage.responses[index]
        except IndexError:
            return (500, self.page('Error', 'NO SUCH REQUEST: %s' % sys.exc_info()[1]))
        self.storage.next_request = index
        self.storage.mode = self.SEQUENTIAL
        return (200, self.message_page("Request %s set as next" % (index + 1)))

    def find_matching_response(self, req):
        text_to_match_against = "%s %s\r\n%s\r\n%s" % (req.method, req.path, req.headers, req.body)
        for response in self.storage.responses:
            if re.search(response.pattern, text_to_match_against):
                return response
        return None
    
    def handle_visit(self):
        headers = str(self.headers)
        body=self.read_request_body()
        req = Record(path=self.path, method=self.method, headers=headers, body=body, timestamp=time.time())
        self.storage.requests.append(req)
        if self.storage.mode == self.REACTIVE:
            response = self.find_matching_response(req)
            if not response:
                return (500, self.page('Error', 'NO RESPONSE MATCHES THIS REQUEST'))
        else:
            try:
                response = self.storage.responses[self.storage.next_request]
            except IndexError:
                return (500, self.page('Error', 'NO NEXT RESPONSE TO RETURN: %s' % sys.exc_info()[1]))
        if self.storage.mode == self.SEQUENTIAL:
            self.storage.next_request += 1
        return (response.status, response.body, response.content_type)

    def handle_visit_raw(self):
        try:
            index = self.path_arg()
            req = self.storage.responses[index]
        except IndexError:
            return (500, self.page('Error', 'NO SUCH RESPONSE: %s' % sys.exc_info()[1]))
        else:
            return (req.status, req.body, req.content_type)

    def handle_save(self):
        query = self.read_request_body()
        values = cgi.parse_qs(query, True)
        pattern=values['pattern'][0]
        try: re.compile(pattern)
        except: return (500, self.page('Error', 'ILLEGAL PATTERN: %s' % sys.exc_info()[1]))
        try:
            index = self.path_arg()
        except IndexError:
            req = Record()
            self.storage.responses.append(req)
        else:
            req = self.storage.responses[index]
        req.set(status=values['status'][0], body=values['body'][0], content_type=values['content_type'][0], pattern=pattern)
        return (200, self.message_page('Request saved'))

    def handle_add(self):
        body = '''<form method=post action=/save>
            Pattern to match<br><input name="pattern"><br>
            HTTP Status code<br><input name="status" value=200><br>
            Content type<br><input name="content_type" value="text/plain"><br>
            Body<br><textarea cols=80 rows=20 name="body">Request body here (XML / HTML etc.)</textarea>
            <br><input type="submit" value="Save request">'''
        return (200, self.page('Set next response', body))

    def handle_edit(self):
        try:
            index = self.path_arg()
            req = self.storage.responses[index]
        except IndexError:
            return (500, self.page('Error', 'NO SUCH RESPONSE TO EDIT: %s' % sys.exc_info()[1]))
        body = '''<form method=post action=/save/%d>
            Pattern to match<br><input name="pattern" value=%s><br>
            HTTP Status code<br><input name="status" value=%s><br>
            Content type<br><input name="content_type" value="%s"><br>
            Body<br><textarea cols=80 rows=20 name="body">%s</textarea>
            <br><input type="submit" value="Save request">''' % (index, req.pattern, req.status, req.content_type, cgi.escape(req.body))
        return (200, self.page('Edit response %s' % (index,), body))

    def handle_show(self):
        try:
            index = self.path_arg()
            req = self.storage.requests[index]
        except IndexError:
            return (500, self.page('Error', 'NO SUCH REQUEST TO SHOW: %s' % sys.exc_info()[1]))
        body = "%s %s at %s\n%s\n%s" % (req.method, req.path, time.ctime(req.timestamp), req.headers, req.body)
        return (200, self.page("Request %s" % (index + 1), body, escape=True))

    def handle_clear_requests(self):
        self.storage.next_request = 0
        self.storage.requests = []
        return (200, self.message_page('Received requests cleared'))

    def handle_clear_responses(self):
        self.storage.next_request = 0
        self.storage.sticky = False
        self.storage.responses = []
        return (200, self.message_page('Preset responses cleared'))

    def handle_set_mode(self):
        self.storage.mode = self.path_arg()
        if self.storage.mode != self.REACTIVE and self.storage.next_request >= len(self.storage.responses):
            self.storage.next_request = 0
        return (200, self.message_page('Mode changed'))

    def respond(self, code, body, content_type='text/html'):
        self.wfile.write('\r\n'.join([
            'HTTP/1.0 %s description' % code,
            'Content-Type: %s' % content_type,
            'Content-Length: %d' % len(body),
            'Expires: Mon, 26 Jul 1997 05:00:00 GMT',
            'Cache-Control: no-store, no-cache, must-revalidate',
            'Cache-Control: post-check=0, pre-check=0',
            'Pragma: no-cache', '', body]))
        self.log_request(code, len(body))

    def message_page(self, message):
        return self.page(message, '<a href="/">Back to main menu</a>')

    def page(self, title, body='', escape=False):
        menu_html = " | ".join(['<a href="%(url)s">%(title)s</a>' % entry for entry in self.MENU])
        def mode_link(key, value):
            if self.storage.mode == value: return "<strong>" + key + "</strong>"
            else: return '<a href="/set_mode/%(value)s">%(key)s</a>' % locals()
        mode_html = " | ".join([mode_link(*entry) for entry in self.MODES.items()])
        if escape: body = '<pre>' + cgi.escape(body) + '</pre>'
        return '<html><head><title>%(title)s</title></head><body><table width="100%%">' \
               '<tr><td align="left">%(menu_html)s</td><td align="right">Mode: %(mode_html)s</td></tr>' \
               '</table><hr noshade size=1><h1>%(title)s</h1>%(body)s</body></html>' % locals()

if __name__ == '__main__':
    try:
        HTTPStubRequestHandler.port = int(sys.argv[1])
    except:
        print "usage:", sys.argv[0], "[port]"
        sys.exit(1)
    HTTPStubRequestHandler.storage_filename = os.path.join(tempfile.gettempdir(), "httpstub-%d.dat" % HTTPStubRequestHandler.port)
    print "starting up with storage file", HTTPStubRequestHandler.storage_filename
    BaseHTTPServer.HTTPServer(('', HTTPStubRequestHandler.port), HTTPStubRequestHandler).serve_forever()