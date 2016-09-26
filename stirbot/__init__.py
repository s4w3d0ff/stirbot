#!/usr/bin/python
import time
import re
import logging
import socket
import ssl
from logging.handlers import RotatingFileHandler
from multiprocessing.dummy import Pool, Process
from multiprocessing import cpu_count

SSLPORTS = [6697, 7000, 7070]
NONSSLPORTS = [6665, 6666, 6667, 8000, 8001, 8002]

class CommandHandle(object):
    """ Base Class for commands """
    def __init__(self, regex, function):
        if not isinstance(regex, list):
            regex = [regex]
        self.regex = regex
        self.function = function
        self.cregex = []

class Channel(object):
    """ Base class for channels"""
    def __init__(self):
        self.users = {}
        #{'name': 'ACC level'},
        self.ops = []
        self.voices = []
        self.modes = []
        self.topic = ""

class IRCServer(object):
    """ Manages Irc server connection """
    def __init__(
                self, nick, host="chat.freenode.net",
                autojoin=['#stirbot'], ssl=False, timeout=60*4,
                threads=cpu_count()**3, pswrd=False
                ):
        self.nick, self.host, self.pswrd  = nick, host, pswrd
        self.ssl, self.threads = ssl, threads
        if not self.ssl:
            self.port = 6666
        else:
            self.port = 7070
        self.timeout, self.threads = timeout, threads
        self._listenThread = self._sock = None
        self._connected = self._running = self._authed = False
        self.channels, self.joinChans = {}, autojoin
        self.commands = {}
        self._pool = Pool(int(self.threads))
        self._listenPool = Pool(int(self.threads))
        self.nickserv = 'NickServ!NickServ@services.'
        self.servHost = None
#-------------------------------------------------------------------------------
        self._serverRe = {
                '_002': CommandHandle(r'^:(.*) 002 (.*) :.*', self._got002),
                '_Ping': CommandHandle(r'^PING :(.*)', self._pong),
                '_Sniff': CommandHandle(
                        [
                            r'^:(.*)!(.*) PRIVMSG (.*) :(.*)',
                            r'^:(.*)!(.*) NOTICE (.*) :(.*)'
                        ],
                        self._sniffMessage
                        ),
                '_332': CommandHandle(
                        [
                            r'^:(.*) 332 %s (.*) :(.*)' % self.nick,
                            r'^:(.*) TOPIC (.*) :(.*)'
                        ],
                        self._updateTopic
                        ),
                '_353': CommandHandle(
                        r'^:.* 353 %s . (.*) :(.*)' % self.nick,
                        self._updateNames
                        ),
                '_Quit': CommandHandle(
                        r'^:(.*)!.* QUIT :', self._somebodyQuit
                        ),
                '_Modeset':    CommandHandle(
                        r'^:.* MODE (.*) \+([A-Za-z]) (.*)', self._modeSet
                        ),
                '_Modeunset': CommandHandle(
                        r'^:.* MODE (.*) -([A-Za-z]) (.*)', self._modeUnset
                        ),
                '_Join': CommandHandle(
                        r'^:(.*)!.* JOIN (.*)', self._joinedUser
                        ),
                '_Part': CommandHandle(
                        r'^:(.*)!.* PART (.*) :.*', self._removeUser
                        ),
                '_ACC':    CommandHandle(
                        r'^:(.+) NOTICE %s :(.+) ACC (\d)(.*)?' % self.nick,
                        self._updateACC
                        ),
                '_Identify': CommandHandle(
                        r'^:(.+) NOTICE (.+) :You are now identified for',
                        self._identified
                        )
                }

    def _got002(self, match):
        """ Fills Serverhost name attribute"""
        if match.group(2) == self.nick:
            self.servHost = match.group(1)
            logging.info("Our server host is: %s" % self.servHost)

    def _pong(self, match):
        """ Pong the Ping """
        logging.debug(match.group(0))
        if match.group(1) == self.servHost:
            self._send("PONG :%s" % self.servHost)

    def _identified(self, match):
        """ Tells the bot it is authenticated with Nickserv """
        logging.debug(match.group(0))
        if match.group(1) == self.nickserv and match.group(2) == self.nick:
            self._authed = True
            logging.info('%s is authenticated with Nickserv!' % self.nick)

    def _joinedUser(self, match):
        """ Fires when a user joins a channel """
        logging.debug(match.group(0))
        nick, channel = match.group(1), match.group(2)
        if channel not in self.channels:
            self.channels[channel] = Channel()
        self.channels[channel].users[nick] = 0
        logging.info('%s joined %s' % (nick, channel))

    def _somebodyQuit(self, match):
        """ Fires when a user quits """
        logging.debug(match.group(0))
        nick = match.group(1)
        # if it is us quiting
        if nick == self.nick:
            self.disconnect()
        else:
            for channel in self.channels:
                if nick in self.channels[channel].users:
                    del self.channels[channel].users[nick]
                if nick in self.channels[channel].ops:
                    del self.channels[channel].ops[nick]
                if nick in self.channels[channel].voices:
                    del self.channels[channel].voices[nick]
        logging.info('%s quit!' % nick)

    def _removeUser(self, match):
        """ Removes a user from a channel """
        logging.debug(match.group(0))
        nick, channel = match.group(1), match.group(2)
        if nick is self.nick:
            del self.channels[channel]
        else:
            del self.channels[channel].users[nick]
            if nick in self.channels[channel].ops:
                del self.channels[channel].ops[nick]
            if nick in self.channels[channel].voices:
                del self.channels[channel].voices[nick]
        logging.info('%s parted %s' % (nick, channel))
        logging.debug(self.channels[channel].users)

    def _updateTopic(self, match):
        """ Update the topic for a channel """
        logging.debug(match.group(0))
        host, channel, topic = match.group(1), match.group(2), match.group(3)
        if channel not in self.channels:
            self.channels[channel] = Channel()
        self.channels[channel].topic = topic
        logging.info('[%s] TOPIC: %s' % (channel, self.channels[channel].topic))

    def _updateNames(self, match):
        """ Takes names from a 353 and populates the channels users """
        logging.debug(match.group(0))
        channel, names = match.group(1), match.group(2).split(' ')
        if channel not in self.channels:
            self.channels[channel] = Channel()
        for name in names:
            if name[0] == '@':
                name = name[1:]
                if name not in self.channels[channel].ops:
                    self.channels[channel].ops.append(name)
            if name[0] == '+':
                name = name[1:]
                if name not in self.channels[channel].voices:
                    self.channels[channel].voices.append(name)
            if name not in self.channels[channel].users:
                self.channels[channel].users[name] = 0
        logging.info('[%s] USERS: %s' % (
                channel, str(self.channels[channel].users)
                ))
        logging.info('[%s] OPS: %s' % (
                channel, str(self.channels[channel].ops)
                ))
        logging.info('[%s] VOICES: %s' % (
                channel, str(self.channels[channel].voices)
                ))

    def _updateACC(self, match):
        """ Updates an users ACC level """
        logging.debug(match.group(0))
        nick, acc = match.group(2), match.group(3)
        if match.group(1) == self.nickserv:
            for channel in self.channels:
                self.channels[channel].users[nick] = acc
        logging.info('ACC: %s [%d]' % (nick, acc))

    def _modeSet(self, match):
        """ Adds mode flags to a user in the CHANNELS dict """
        logging.debug(match.group(0))
        channel, mode, nick = match.group(1), match.group(2), match.group(3)
        if 'o' in mode or 'O' in mode:
            if nick not in self.channels[channel].ops:
                self.channels[channel].ops.append(nick)
        if 'v' in mode or 'V' in mode:
            if nick not in self.channels[channel].voices:
                self.channels[channel].voices.append(nick)
        logging.debug('OPS: %s' % str(self.channels[channel].ops))
        logging.debug('VOICES: %s' % str(self.channels[channel].voices))

    def _modeUnset(self, match):
        """ Removes mode flags from a user in the CHANNELS dict """
        logging.debug(match.group(0))
        channel, mode, nick = match.group(1), match.group(2), match.group(3)
        if 'o' in mode or 'O' in mode:
            try:
                self.channels[channel].ops.remove(nick)
            except Exception as e:
                logging.exception(e)
        if 'v' in mode or 'V' in mode:
            try:
                self.channels[channel].voices.remove(nick)
            except Exception as e:
                logging.exception(e)
        logging.debug('OPS: %s' % str(self.channels[channel].ops))
        logging.debug('VOICES: %s' % str(self.channels[channel].voices))
#-------------------------------------------------------------------------------
    def sendMessage(self, target, message):
        """ Send a message """
        self._send("PRIVMSG %s :%s" % (target, message))

    def sendNotice(self, target, message):
        """ Send a notice """
        self._send("NOTICE %s :%s" % (target, message))

    def checkACC(self, nick):
        """ Check the acc level of a nick """
        self._send("NICKSERV ACC %s" % nick)

    def joinChannel(self, channel):
        """ Join a channel """
        self._send("JOIN %s" % channel)

    def partChannel(self, channel):
        """ Leave a channel """
        self._send("PART %s" % channel)

    def setNick(self, nick):
        """ Change nickname """
        self.nick = nick
        self.compileRe()
        self._send("NICK %s" % nick)
        logging.info('Nick changed!')

    def setChannelTopic(self, channel, topic):
        """ Change channel topic """
        self._send("TOPIC %s :%s" % (channel, topic))

    def kickUser(self, channel, nick, message):
        """ Kick a user """
        self._send("KICK %s %s :%s" % (channel, nick, message))

    def quit(self, message="I'll be back!"):
        """ Send quit message """
        self._send("QUIT :%s" % message)

#-------------------------------------------------------------------------------
    def loadCommands(self, commands):
        """
        Loads a dict as self.commands and compiles regex (overwrites all)
        """
        logging.info('Loading commands')
        self.commands = commands
        self._pool.map(self._compileCommandRe, self.commands)

    def addCommand(self, name, regex, func):
        """
        Add a command to the self.commands dict
        (overwrites commands with the same <name>)
        """
        self.commands[name] = CommandHandle(regex, func)
        self._compileCommandRe(name)
        logging.info('Command: %s added!' % name)

    def removeCommand(self, name):
        """ Remove <name> command from the self.commands dict """
        del self.commands[name]
        logging.info('Command: %s removed!' % name)

#-------------------------------------------------------------------------------
    def _compileServerRe(self, command):
        """ Compiles single server regex by command name """
        self._serverRe[command].cregex = []
        logging.debug(self._serverRe[command].regex)
        for item in self._serverRe[command].regex:
            self._serverRe[command].cregex.append(re.compile(item))

    def _compileCommandRe(self, command):
        """ Compiles single command regex by command name """
        self.commands[command].cregex = []
        logging.debug(self.commands[command].regex)
        for item in self.commands[command].regex:
            self.commands[command].cregex.append(re.compile(item))

    def compileRe(self):
        """ Uses the thread pool to compile all the commands regex """
        logging.info('Compiling regex!')
        self._pool.map(self._compileServerRe, self._serverRe)
        self._pool.map(self._compileCommandRe, self.commands)

    def _autoJoin(self):
        """ Join all the channels in self.autojoin """
        for chan in self.joinChans:
            logging.info('Auto joining: %s' % chan)
            self.joinChannel(chan)
#-------------------------------------------------------------------------------
    def _sniffLine(self, line):
        """
        Searches the line for anything relevent
        executes the function for the match
        """
        match = False
        for name in self._serverRe:
            for item in self._serverRe[name].cregex:
                match = item.search(line)
                if match:
                    self._serverRe[name].function(match)
                    return True

    def _sniffMessage(self, match):
        """
        Search PRIVMESG/NOTICE for a command
        executes the function for the match
        """
        nick, host, chan, message = \
                match.group(1), match.group(2), match.group(3), match.group(4)
        cmatch = False
        logging.info('[%s] %s: %s' % (chan, nick, message))
        for name in self.commands:
            for regex in self.commands[name].cregex:
                cmatch = regex.search(message)
                if cmatch:
                    self.commands[name].function(chan, nick, host, cmatch)
                    return True
#-------------------------------------------------------------------------------
    def _identifyNick(self, pswrd):
        """ Identify bot nickname with nickserv """
        self._send("NICKSERV IDENTIFY %s" % (pswrd))

    def auth(self, nick):
        """ Login to the IRC server and identify with nickserv"""
        logging.info('Authenticating bot with server...')
        self._send(
            "USER %s %s %s :This bot is a result of open-source development." %\
                    (nick, nick, nick)
            )
        self._send("NICK %s" % nick)
        if self.pswrd:
            logging.debug('We have a nick password!')
            self._identifyNick(self.pswrd)
            logging.info('Waiting on Nickserv...')
            count = 0
            while not self._authed:
                time.sleep(5)
                count += 1
                if count > 5:
                    raise RuntimeError('Failed to auth with Nickserv')
        else:
            self._authed = True

    def _send(self, message):
        """ Sends a message to IRC server """
        logging.debug("> %s" % message)
        message = "%s\r\n" % message
        try:
            self._sock.send(message.encode("utf-8"))
        except (socket.timeout, socket.error, ssl.SSLError) as e:
            logging.warning("Socket Error: Could not send!")
            logging.exception(e)
            self._connected = False
        except Exception as e:
            logging.exception(e)
            self._connected, self._running = False, False

    def _listen(self):
        """ This should be running in a thread """
        logging.info('Listening...')
        while self._connected:
            try:
                data = self._sock.recv(4096)
            except (socket.timeout, ssl.SSLError) as e:
                if 'timed out' in e.args[0]:
                    continue
                else:
                    logging.exception(e)
                    self._connected = False
                    continue
            except socket.error as e:
                logging.exception(e)
                self._connected = False
                continue
            else:
                if len(data) == 0:
                    logging.warn('Listen socket closed!')
                    self._connected = False
                    continue
                try:
                    data = data.strip(b'\r\n').decode("utf-8")
                    self._listenPool.map(self._sniffLine, data.splitlines())
                except Exception as e:
                    logging.exception(e)
                    continue
        self._listenPool.join()
        logging.info('No longer listening...')

    def connect(self):
        """Connect the socket to the server and listen"""
        while not self._connected:
            logging.info("Connecting to %s:%s" % (self.host, str(self.port)))
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2)
            if not self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE):
                logging.debug('Keeping socket alive')
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if self.ssl:
                self._sock = ssl.wrap_socket(self._sock)
            try:
                self._sock.connect((self.host, self.port))
            except (socket.timeout, socket.error, ssl.SSLError) as e:
                logging.exception(e)
                time.sleep(1.0)
                continue
            except Exception as e:
                logging.exception(e)
                self._connected, self._running = False, False
            else:
                logging.info("Connected!")
                self._connected = True

    def disconnect(self):
        """ Disconnect from the server """
        logging.info('Disconnecting...')
        self._connected, self._running, self._authed = False, False, False
        self.servHost, self.channels = None, {}
        try:
            self._pool.close()
            self._listenPool.close()
        except Exception as e:
            logging.exception(e)
        logging.debug('Pool closed')
        try:
            self._pool.join()
        except Exception as e:
            logging.exception(e)
        logging.debug('Pool joined')
        self._pool = Pool(self.threads)
        logging.debug('Pool cleared')
        try:
            self._listenThread.join()
        except Exception as e:
            logging.exception(e)
        logging.debug('Listen Thread joined(?)')
        try:
            self._sock.close()
        except Exception as e:
            logging.exception(e)
        logging.debug('Socket closed(?)')
        logging.info('Disconnected!')

    def __call__(self):
        """ Starts the connection to the server """
        self._running = True
        while self._running:
            self.compileRe()
            self._listenThread = Process(name='Listener', target=self._listen)
            self._listenThread.daemon = True
            try:
                self.connect()
                self._listenThread.start()
                self.auth(self.nick)
            except:
                self.disconnect()
                continue
            self._autoJoin()
            while self._connected:
                try:
                    time.sleep(0.5)
                except:
                    self.disconnect()

if __name__ == "__main__":
    logging.basicConfig(
            format='[%(asctime)s] %(message)s',
            datefmt="%m-%d %H:%M:%S",
            level=logging.DEBUG
            )
    logger = logging.getLogger()
    logger.addHandler(
            RotatingFileHandler('ircbot.log', maxBytes=10**9, backupCount=5)
            )
    bot = IRCServer('s10tb0t', ssl=True)
    def shutit(channel, nick, host, match):
        bot.sendMessage(channel, '%s asked me to quit! See ya!' % nick)
        bot._running = False
        bot.quit()
    bot.addCommand('Quit', r'^!quit', shutit)
    bot()
