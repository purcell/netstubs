#!/usr/bin/env/python

import asyncore, sys, smtpd  ## Some languages just have decent standard libraries... ;)

if __name__ == '__main__':
    progname = sys.argv[0]
    args = sys.argv[1:]
    if len(args) > 1 or args in (['-h'], ['-help'], ['--help']):
        print """Usage: %(progname)s [port]
        Where 'port' is SMTP port number, 25 by default. """ % locals()
        sys.exit(1)

    if args: port = int(args[0])
    else: port = 25
    s = smtpd.DebuggingServer(('localhost', port), None)
    print "smtpstub starting on port", port
    asyncore.loop()