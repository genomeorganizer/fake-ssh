#!/usr/bin/env python
"""Fake SSH Server Utilizing Paramiko"""
import argparse
import threading
import socket
import sys
import os
import traceback
import paramiko
import json
from getmac import get_mac_address

import email_alerts

def load_auth_file(filename):
    with open(filename, "r") as auth_file:
        auth = json.load(auth_file)
        return auth

LOG = open("/usr/local/bin/fake-ssh/logs/log.txt", "a")
HOST_KEY = paramiko.RSAKey(filename='/usr/local/bin/fake-ssh/keys/private.key')
SSH_BANNER = "SSH-2.0-OpenSSH_8.2p1 Ubuntu-4ubuntu0.1"


def handle_cmd(cmd, chan):
    """Branching statements to handle and prepare a response for a command"""
    response = ""
    if cmd.startswith("ls"):
        response = "Desktop Documents Pictures Music Shared"
    elif cmd.startswith("version"):
        response = """GNU bash, version 3.1.27(1)-release (x86_64)
Copyright (C) 2007 Free Software Foundation, Inc."""
    elif cmd.startswith("pwd"):
        response = "/home/user"
    elif cmd.startswith("rm"):
        response = "-bash: {} not found"
    else:
        response = "-bash: "+cmd+" command not found"
    LOG.write(response + "\n")
    LOG.flush()
    chan.send(response + "\r\n")


def send_ascii(filename, chan):
    """Print ascii from a file and send it to the channel"""
    with open('ascii/{}'.format(filename)) as text:
        chan.send("\r")
        for line in enumerate(text):
            LOG.write(line[1])
            chan.send(line[1] + "\r")
    LOG.flush()


class FakeSshServer(paramiko.ServerInterface):
    """Settings for paramiko server interface"""
    def __init__(self):
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        # Accept all passwords as valid by default
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


def handle_connection(client, addr):
    """Handle a new ssh connection"""
    ip = str(addr[0])
    mac = get_mac_address(ip=str(addr[0]))
    msg = "Connection from ip: "+ip+" mac: "+mac
    LOG.write("\n\n"+msg+"\n")#Connection from: " + addr[0] + "\n")
    print('Got a connection!')
    a=load_auth_file("/usr/local/bin/email.json")
    try:
        email_alerts.send(auth=a,to=mail,subject="ALERT! SSH Connection attempt to fake-ssh on port 22 from: " + addr[0],message=msg)
        print("Sent email")
    except:
        print("unable to send alert")
    try:
        transport = paramiko.Transport(client)
        transport.add_server_key(HOST_KEY)
        # Change banner to appear legit on nmap (or other network) scans
        transport.local_version = SSH_BANNER
        server = FakeSshServer()
        try:
            transport.start_server(server=server)
        except paramiko.SSHException:
            print('*** SSH negotiation failed.')
            raise Exception("SSH negotiation failed")
        # wait for auth
        chan = transport.accept(20)
        if chan is None:
            print('*** No channel.')
            raise Exception("No channel")

        server.event.wait(10)
        if not server.event.is_set():
            print('*** Client never asked for a shell.')
            raise Exception("No shell request")

        try:
            chan.send("""###############################################################\r\n
    Welcome to Ubuntu Server Version 20.0.1\r\n
    All connections are monitored and recorded\r\n
    Disconnect IMMEDIATELY if you are not an authorized user!\r\n
###############################################################\r\n
            \r\n""")
            run = True
            while run:
                chan.send("$ ")
                command = ""
                while not command.endswith("\r"):
                    transport = chan.recv(1024)
                    # Echo input to psuedo-simulate a basic terminal
                    chan.send(transport)
                    command += transport.decode("utf-8")

                chan.send("\r\n")
                command = command.rstrip()
                LOG.write("$ " + command + "\n")
                print(command)
                if command == "exit":
                    run = False
                else:
                    handle_cmd(command, chan)

        except Exception as err:
            print('!!! Exception: {}: {}'.format(err.__class__, err))
            traceback.print_exc()
            try:
                transport.close()
            except Exception:
                pass

        chan.close()

    except Exception as err:
        print('!!! Exception: {}: {}'.format(err.__class__, err))
        traceback.print_exc()
        try:
            transport.close()
        except Exception:
            pass


def start_server(port, bind):
    """Init and run the ssh server"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind, port))
    except Exception as err:
        print('*** Bind failed: {}'.format(err))
        traceback.print_exc()
        sys.exit(1)

    threads = []
    while True:
        try:
            sock.listen(100)
            print('Listening for connection ...')
            client, addr = sock.accept()
        except Exception as err:
            print('*** Listen/accept failed: {}'.format(err))
            traceback.print_exc()
        new_thread = threading.Thread(target=handle_connection, args=(client, addr))
        new_thread.start()
        threads.append(new_thread)

    for thread in threads:
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run a fake ssh server')
    parser.add_argument("--port", "-p", help="The port to bind the ssh server to (default 22)", default=22, type=int, action="store")
    parser.add_argument("--bind", "-b", help="The address to bind the ssh server to", default="", type=str, action="store")
    parser.add_argument("--mail", "-m", help="notification email", default="", type=str, action="store")
    args = parser.parse_args()
    mail = args.mail
    start_server(args.port, args.bind)