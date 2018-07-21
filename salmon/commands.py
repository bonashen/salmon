"""
Documentation for this module can be found in :doc:`commandline`
"""

from __future__ import print_function, unicode_literals

import email
import glob
import mailbox
import os
import shutil
import signal
import sys

import click

from salmon import server, utils, mail, routing, queue as queue_module, encoding
import salmon


DEFAULT_PID_FILE = "./run/stmp.pid"

copyright_notice = """
Salmon is Copyright (C) Matt Molyneaux 2014-2015.  Licensed GPLv3.
Forked from Lamon, Copyright (C) Zed A. Shaw 2008-2009.  Licensed GPLv3.
If you didn't get a copy of the LICENSE go to:

    https://github.com/moggers87/salmon/LICENSE

Have fun.
"""

uid_desc = """
If you specify a uid/gid then this means you want to first change to
root, set everything up, and then drop to that UID/GID combination.
This is typically so you can bind to port 25 and then become "safe"
to continue operating as a non-root user. If you give one or the other,
this it will just change to that uid or gid without doing the priv drop
operation.
"""


@click.group(epilog=copyright_notice)
@click.version_option()
def main():
    """Python mail server"""
    pass


@main.command(short_help="starts log server", epilog=uid_desc)
@click.option("--port", default=8825, type=int, help="port to listen on")
@click.option("--host", default="127.0.0.1", help="address to listen on")
@click.option("--chroot", help="path to chroot")
@click.option("--chdir", default=".", help="change to this directory when daemonising")
@click.option("--umask", type=int, help="set umask on server")
@click.option("--pid", default="./run/log.pid", help="path to pid file")
@click.option("-f", "--force", default=False, is_flag=True, help="force server to run, ignoring pid file")
@click.option("--debug", default=False, is_flag=True, help="debug mode")
@click.option("--uid", type=int, help="run with this user id")
@click.option("--gid", type=int, help="run with this group id")
@click.option("--daemon/--no-daemon", default=True, help="start server as daemon (default)")
def log(port, host, pid, chdir, chroot=None, uid=False, gid=False, umask=False,
        force=False, debug=False, daemon=True):
    """
    Runs a logging only server on the given hosts and port.  It logs
    each message it receives and also stores it to the run/queue
    so that you can make sure it was received in testing.
    """
    utils.start_server(pid, force, chroot, chdir, uid, gid, umask,
                       lambda: utils.make_fake_settings(host, port), debug, daemon)


@main.command(short_help="send a new email")
@click.option("--port", default=8825, type=int, help="Port to connect to")
@click.option("--host", default="127.0.0.1", help="Host to connect to")
@click.option("--username", help="SMTP username")
@click.option("--password", help="SMTP password")
@click.option("--sender", metavar="EMAIL")
@click.option("--to", metavar="EMAIL")
@click.option("--subject")
@click.option("--body")
@click.option("--attach")
@click.option("--lmtp", default=False)
@click.option("--ssl", default=False)
@click.option("--starttls", default=False)
def send(port, host, username=None, password=None, ssl=None, starttls=None, lmtp=None,
         sender=None, to=None, subject=None, body=None, attach=None):
    """
    Sends an email to someone as a test message.
    See the sendmail command for a sendmail replacement.
    """
    message = mail.MailResponse(From=sender, To=to, Subject=subject, Body=body)
    if attach:
        message.attach(attach)

    relay = server.Relay(host, port=port, username=username, password=password, ssl=ssl,
                         starttls=starttls, lmtp=lmtp, debug=False)
    relay.deliver(message)


@main.command(short_help="send an email from stdin")
@click.option("--port", default=8825, type=int, help="Port to listen on")
@click.option("--host", default="127.0.0.1", help="Address to listen on")
@click.option("--lmtp", default=False, is_flag=True, help="Use LMTP rather than SMTP")
@click.option("--debug", default=False, is_flag=True, help="Debug mode")
@click.argument("recipients", nargs=-1, required=True)
def sendmail(port, host, recipients, debug=False, lmtp=False):
    """
    Used as a testing sendmail replacement for use in programs
    like mutt as an MTA.  It reads the email to send on the stdin
    and then delivers it based on the port and host settings.
    """
    relay = server.Relay(host, port=port, debug=debug, lmtp=lmtp)
    data = sys.stdin.read()
    msg = mail.MailRequest(None, recipients, None, data)
    relay.deliver(msg)


@main.command(short_help="starts a server", epilog=uid_desc)
@click.option("--boot", default="config.boot", help="module with server definition")
@click.option("--chroot", help="path to chroot")
@click.option("--chdir", default=".", help="change to this directory when daemonising")
@click.option("--umask", type=int, help="set umask on server")
@click.option("--pid", default=DEFAULT_PID_FILE, help="path to pid file")
@click.option("-f", "--force", default=False, is_flag=True, help="force server to run, ignoring pid file")
@click.option("--debug", default=False, is_flag=True, help="debug mode")
@click.option("--uid", type=int, help="run with this user id")
@click.option("--gid", type=int, help="run with this group id")
@click.option("--daemon/--no-daemon", default=True, help="start server as daemon (default)")
def start(pid, force, chdir, boot, chroot=False, uid=False, gid=False, umask=False, debug=False, daemon=True):
    """
    Runs a salmon server out of the current directory
    """
    utils.start_server(pid, force, chroot, chdir, uid, gid, umask,
                       lambda: utils.import_settings(True, boot_module=boot), debug, daemon)


@main.command(short_help="stops a server")
@click.option("--pid", default=DEFAULT_PID_FILE, help="path to pid file")
@click.option("-f", "--force", default=False, is_flag=True, help="force stop server")
@click.option("--all", default=False, help="stops all servers with .pid files in the specified directory")
def stop(pid, force=False, all=False):
    """
    Stops a running salmon server
    """
    pid_files = []

    if all:
        pid_files = glob.glob(all + "/*.pid")
    else:
        pid_files = [pid]

        if not os.path.exists(pid):
            click.echo("PID file %s doesn't exist, maybe Salmon isn't running?" % pid)
            sys.exit(1)
            return  # for unit tests mocking sys.exit

    click.echo("Stopping processes with the following PID files: %s" % pid_files)

    for pid_f in pid_files:
        pid = open(pid_f).readline()

        click.echo("Attempting to stop salmon at pid %d" % int(pid))

        try:
            if force:
                os.kill(int(pid), signal.SIGKILL)
            else:
                os.kill(int(pid), signal.SIGHUP)

            os.unlink(pid_f)
        except OSError as exc:
            click.echo("ERROR stopping Salmon on PID %d: %s" % (int(pid), exc))


@main.command(short_help="displays status of server")
@click.option("--pid", default=DEFAULT_PID_FILE, help="path to pid file")
def status(pid):
    """
    Prints out status information about salmon useful for finding out if it's
    running and where.
    """
    if os.path.exists(pid):
        pid = open(pid).readline()
        click.echo("Salmon running with PID %d" % int(pid))
    else:
        click.echo("Salmon not running.")


@main.command(short_help="manipulate a Queue")
@click.option("--pop", default=False, is_flag=True, help="pop a message from queue")
@click.option("--get", metavar="KEY", help="get key from queue")
@click.option("--remove", metavar="KEY", help="remove chosen key from queue")
@click.option("--count", default=False, is_flag=True, help="count messages in queue")
@click.option("--clear", default=False, is_flag=True, help="clear queue")
@click.option("--keys", default=False, is_flag=True, help="print queue keys")
@click.argument("name", default="./run/queue", metavar="queue")
def queue(name, pop=False, get=False, keys=False, remove=False, count=False, clear=False):
    """
    Lets you do most of the operations available to a queue.
    """
    click.echo("Using queue: %r" % name)

    inq = queue_module.Queue(name)

    if pop:
        key, msg = inq.pop()
        if key:
            click.echo("KEY: %s" % key)
            click.echo(msg)
    elif get:
        click.echo(inq.get(get))
    elif remove:
        inq.remove(remove)
    elif count:
        click.echo("Queue %s contains %d messages" % (name, inq.count()))
    elif clear:
        inq.clear()
    elif keys:
        click.echo("\n".join(inq.keys()))


@main.command(short_help="display routes")
@click.option("--path", default=os.getcwd, help="search path for modules")
@click.option("--test", metavar="EMAIL", help="test address")
@click.argument("modules", metavar="module", default=["config.testing"])
def routes(modules, path=None, test=""):
    """
    Prints out valuable information about an application's routing configuration
    after everything is loaded and ready to go.  Helps debug problems with
    messages not getting to your handlers.  Path has the search paths you want
    separated by a ':' character, and it's added to the sys.path.
    """
    sys.path += path.split(':')
    test_case_matches = []

    for module in modules:
        __import__(module, globals(), locals())

    click.echo("Routing ORDER: %s" % routing.Router.ORDER)
    click.echo("Routing TABLE: \n---")
    for format in routing.Router.REGISTERED:
        click.echo("%r: " % format, nl=False)
        regex, functions = routing.Router.REGISTERED[format]
        for func in functions:
            click.echo("%s.%s " % (func.__module__, func.__name__), nl=False)
            match = regex.match(test)
            if test and match:
                test_case_matches.append((format, func, match))

        click.echo("\n---")

    if test_case_matches:
        click.echo("\nTEST address %r matches:" % test)
        for format, func, match in test_case_matches:
            click.echo("  %r %s.%s" % (format, func.__module__, func.__name__))
            click.echo("  -  %r" % (match.groupdict()))
    elif test:
        click.echo("\nTEST address %r didn't match anything." % test)


@main.command(short_help="generate a new project")
@click.argument("project")
@click.option("-f", "--force", is_flag=True, help="overwrite existing directories")
def gen(project, force=False):
    """
    Generates various useful things for you to get you started.
    """
    template = os.path.join(salmon.__path__[0], "data", "prototype")

    if os.path.exists(project) and not force:
        print("Project %s exists, delete it first." % project)
        sys.exit(1)
        return
    elif force:
        shutil.rmtree(project, ignore_errors=True)

    shutil.copytree(template, project)


@main.command(short_help="cleanse your emails")
@click.argument("inbox")
@click.argument("outbox")
def cleanse(inbox, outbox):
    """
    Uses Salmon mail cleansing and canonicalization system to take an
    input Maildir (or mbox) and replicate the email over into another
    Maildir.  It's used mostly for testing and cleaning.
    """
    error_count = 0

    try:
        inbox = mailbox.mbox(inbox)
    except IOError:
        inbox = mailbox.Maildir(inbox, factory=None)

    outbox = mailbox.Maildir(outbox)

    for msg in inbox:
        try:
            mail = encoding.from_message(msg)
            outbox.add(encoding.to_string(mail))
        except encoding.EncodingError as exc:
            click.echo("ERROR: %s" % exc)
            error_count += 1

    outbox.close()
    inbox.close()

    click.echo("TOTAL ERRORS: %s" % error_count)


@main.command(short_help="blast emails at a server")
@click.argument("input")
@click.option("--port", default=8823, type=int, help="port to listen on")
@click.option("--host", default="127.0.0.1", help="address to listen on")
@click.option("--lmtp", default=False, is_flag=True)
@click.option("--debug", default=False, is_flag=True, help="debug mode")
def blast(input, host, port, lmtp=None, debug=False):
    """
    Given a Maildir, this command will go through each email
    and blast it at your server.  It does nothing to the message, so
    it will be real messages hitting your server, not cleansed ones.
    """
    try:
        inbox = mailbox.mbox(input)
    except IOError:
        inbox = mailbox.Maildir(input, factory=None)

    relay = server.Relay(host, port=port, lmtp=lmtp, debug=debug)

    for key in inbox.keys():
        msgfile = inbox.get_file(key)
        msg = email.message_from_file(msgfile)
        relay.deliver(msg)
