#!/usr/bin python
import sys
import time
import re
import ssl
import socket
import logging
from logging.handlers import RotatingFileHandler
from multiprocessing.dummy import Pool, Process
from multiprocessing import cpu_count

# Setup logger
logging.basicConfig(
        format='[%(asctime)s] %(message)s',
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO
        )
logger = logging.getLogger()
logger.addHandler(RotatingFileHandler(
        'ircbot.log', maxBytes=10**9, backupCount=5
        )) # makes 1Gb log files, 5 files max

class Bot(object):
	""" IRC Bot """
	def __init__(
	        self,
	        server="irc.freenode.net",
	        port=7000,
	        botnick="testbot",
	        pswrd=False,
	        channelist=["#slotbot"],
	        maxthreads=cpu_count()*cpu_count()
	        ):
		"""
		self.server = IRC server address
		self.port = IRC server port
		self.botnick = Nickname to be used by bot
		self.pswrd = Nickserv password
		self.channellist = List of channels to join when bot starts
		self.maxthreads  = Number of threads to have waiting per pool
		
		self.channels = a dict of channels the bot is active in
		- {'#channelName': {
		        'topic': 'Channel Topic', 
		        'users':{
		            'name': 'o,v or 0-3'
		            },,,
		        },,,
		  }
		
		self.commands = user defined dict of regex to look for in privmsgs
		- { 'quit':{
		        'function': quit,
		        'regex': r'!quit'
		        },,,
		  }
		"""
		# Set attributes
		self.server, self.port, self.maxthreads = [server, port, maxthreads]
		self.botnick, self.pswrd  = [botnick, pswrd]
		self.channellist, self._ircsock = [channelist, None]
		# Set flags
		self._connected, self._authed, self._running = [False, False, True]
		# Set up threads
		self._thinkpool, self._listenThread = [Pool(self.maxthreads), None]
		# IRC Server related compiled regex and functions
		self._serverRe = {
			'_Ping': {
			    'function': self._pong,
			    'regex': r'^PING :(.*)'
			    },
			'_Privmsg':	{
			    'function': self._sniffMessage,
			    'regex': r'^:(.*)!~(.*) PRIVMSG (.*) :(.*)'
			    },
			'_Notice': {
			    'function': self._sniffMessage,
			    'regex': r'^:(.*)!~(.*) NOTICE (.*) :(.*)'
			    },
			'_ACC':	{
			    'function': self._updateACC,
			    'regex': r'^:.* NOTICE %s :(.+) ACC (\d)(.*)?' % self.botnick
			    },
			'_Topic1': {
			    'function': self._updateTopic,
			    'regex': r'^:.* 332 %s (.*) :(.*)' % self.botnick
			    },
			'_Topic2': {
			    'function': self._updateTopic,
			    'regex': r'^:.* TOPIC (.*) :(.*)'
			    },
			'_Names': {
			    'function': self._updateNames,
			    'regex': r'^:.* 353 %s . (.*) :(.*)' % self.botnick
			    },
			'_Quit': {
			    'function': self._somebodyQuit,
			    'regex': r'^:(.*)!.* QUIT :'
			    },
			'_Modeset':	{
			    'function': self._modeSet,
			    'regex': r'^:.* MODE (.*) \+([A-Za-z]) (.*)'
			    },
			'_Modeunset': {
			    'function': self._modeUnset,
			    'regex': r'^:.* MODE (.*) -([A-Za-z]) (.*)'
			    },
			'_Join': {
			    'function': self._joinedUser,
			    'regex': r'^:(.*)!.* JOIN (.*)'
			    },
			'_Part': {
			    'function': self._removeUser,
			    'regex': r'^:(.*)!.* PART (.*) :.*'
			    },
			'_Identify': {
			    'function': self._identified,	
			    'regex': r'^:NickServ!NickServ@services. \
			        NOTICE %s :You are now identified for.*' % self.botnick
			    },
			'_Error': {
			    'function': self._serverDisconnect,
			    'regex': r'^ERROR :Closing Link:.*'
			    }
			}
		
		self.channels = self.commands = {}
		
    #-----------------------------------------------------------------------

    def _pong(self, match):
        """ Pong the Ping """
        self._send("PONG :%s" % match.group(1))

    def _identifyNick(pswrd):
        """ Identify bot nickname with nickserv """
        self._send("NICKSERV IDENTIFY %s" % (pswrd))

    #-----------------------------------------------------------------------
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
        self.botnick = nick
        self._send("NICK %s" % nick)

    def setAway(self, message=False):
        """ Set away message or come back from away """
        if message:
            self._send("AWAY :%s" % message)
        else:
            self._send("AWAY ")

    def setMode(self, nick, flags):
        """ Set mode for a nick """
        self._send("MODE %s +%s" % (nick, flags))

    def unsetMode(self, nick, flags):
        """ Unset mode for a nick """
        self._send("MODE %s -%s" % (nick, flags))

    def setChannelTopic(self, channel, topic):
        """ Change channel topic """
        self._send("TOPIC %s :%s" % (channel, topic))

    def kickUser(self, channel, nick, message):
        """ Kick a user """
        self._send("KICK %s %s :%s" % (channel, nick, message))

    def quit(self, message="I'll be back!"):
        """ Send quit message """
        self._send("QUIT :%s" % message)
		
################################################################################
	def _identified(self, match=False):
		""" Tells the bot it is authenticated with Nickserv """
		self._authed = True
		
	def _joinedUser(self, match):
		""" Fires when a user joins a channel """
		if match.group(2) not in self.channels:
			self.channels.update({match.group(2):{}})
		if match.group(1) != self.botnick:
			self._addUser(match.group(2), match.group(1))
		
	def _somebodyQuit(self, match):
		""" Fires when a user quits """
		for channel in self.channels.keys():
			for user in self.channels[channel].keys():
				if self.channels[channel][user].key() == match.group(1):
					del self.channels[channel][user]
		
	def _addUser(self, channel, name):
		""" Adds a user to a channel in the CHANNELS dict """
		self.channels[channel]['users'].update({name:''})
		
	def _removeUser(self, match):
		""" Removes a user from a channel in the CHANNELS dict """
		if match.group(1) is self.botnick:
		    del self.channels[match.group(2)]
		else:
		    del self.channels[match.group(2)]['users'][match.group(1)]
	
	def _updateTopic(self, match):
		""" Update the topic for a channel in the CHANNELS dict """
		if match.group(1) not in self.channels:
		    self.channels.update({match.group(1):{'topic':match.group(2)}})
		else:
		    self.channels[match.group(1)]['topic'] = match.group(2)
		
	def _updateNames(self, match):
		""" Takes names from a 353 and populates the CHANNELS dict """
		channel, names = [match.group(1), match.group(2).split(' ')]
		if not 'users' in self.channels[channel]:
		    self.channels[channel]['users'] = {}
		for name in names:
			if name[0] is '@':
			    self.channels[channel]['users'].update({name[1:]:'o'})
			if name[0] is '+':
			    self.channels[channel]['users'].update({name[1:]:'v'})
			if (name[0] is not '@') and (name[0] is not '+'):
			    self.channels[channel]['users'].update({name:''})
			
	def _updateACC(self, match):
		""" Attempts to update a users mode with an ACC level """
		for channel in self.channels:
			for user in self.channels[channel]['users']:
				mode = self.channels[channel]['users']
				if ('o' not in mode) or ('v' not in mode) \
				            and (match.group(2) is user):
					if not mode or int(mode) < int(match.group(3)):
						self.channels[channel]['users'][user]['mode'] = \
						            match.group(3)
	
	def _modeSet(self, match):
		""" Adds mode flags to a user in the CHANNELS dict """
		channel, mode, nick = [match.group(1), match.group(2), match.group(3)]
		for user in self.channels[channel]['users'].keys():
			if user == nick:
				oldModes = self.channels[channel]['users'][user]
				newModes = mode
				for flag in newModes:
					if flag not in oldModes:
						self.channels[channel]['users'][user] = \
						    self.channels[channel]['users'][user]+flag.lower()
	
	def _modeUnset(self, match):
		""" Removes mode flags from a user in the CHANNELS dict """
		channel, mode, nick = [match.group(1), match.group(2), match.group(3)]
		for user in self.channels[channel]['users'].keys():
			if user == nick:
				for flag in mode.lower():
					self.channels[channel]['users'][user] = \
					    self.channels[channel]['users'][user].replace(flag,'')
					
	#-------------------
	def _compileServerRe(self, command):
		""" Compiles single server regex by cammand name """
		self._serverRe[command]['cregex'] = \
		        re.compile(self._serverRe[command]['regex'])
	
	def _compileCommandRe(self, command):
		""" Compiles single command regex by cammand name """
		self.commands[command]['cregex'] = \
		        re.compile(self.commands[command]['regex'])
	
	def _compileCommands(self):
		""" Uses the thread pool to compile all the commands regex """
		self._thinkpool.map(self._compileServerRe, self._serverRe)
		self._thinkpool.map(self._compileCommandRe, self.commands)
	
	
################################################################################
	
	def _send(self, message):
		""" Sends a message to IRC server """
		logging.info("> %s" % message)
		message = "%s\r\n" % message
		try:
			self._ircsock.send(message.encode("utf-8"))
		except socket.error as e:
			logging.exception(e)
			logging.warn('BAD SOCKET WHILE SENDING!')
			self._connected, self._authed = [False, False]
	
	def _listen(self):
		""" Listen for messages from IRC server """
		logging.info('Listening...')
		while self._connected:
			try:
				data = self._ircsock.recv(4096)
				data = data.strip(b'\r\n').decode("utf-8")
				# Most of the work stems from this function
				# it also will throw the most exceptions
				self._thinkpool.map(self._sniffLine, data.splitlines())
			except socket.error as e:
			    # stop listening if socket throws an exception
				logging.exception(e)
				logging.warn('BAD SOCKET WHILE LISTENING!')
				self._connected, self._authed = [False, False]
				
			except Exception as e: # shutdown bot if unknown error
				logging.exception(e)
				logging.info('Unknown ERROR: Shutting down...')
				self._connected, self._authed, self._running = \
				        [False, False, False]
				
		logging.info('No longer listening...')
	
	def _serverConnect(self):
		""" Create the connection to the IRC server """
		# keep trying socket until connected or not running anymore
		while not self._connected and self._running:
			try:
				logging.info("Connecting...")
				# create socket
				sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				# set timeout
				sock.settimeout(360)
				# wrap socket in ssl
				self._ircsock = ssl.wrap_socket(sock)
				# connect
				self._ircsock.connect((self.server, self.port))
				# tell bot we are connected so we can stop trying
				self._connected = True
				logging.info("Apparently connected...")
				self._listenThread = Process(
				        name='Listener', 
				        target=self._listen
				        )
				self._listenThread.daemon = True
				 # start listening thread
				self._listenThread.start()
		    # keep trying if socket errors
			except socket.error as e:
				logging.warn('BAD SOCKET WHILE CONNECTING!')
				logging.exception(e)
				logging.info("Waiting...")
				time.sleep(10)
		    # if unknown error
			except Exception as e:
				logging.exception(e)
				 # stop the bot completely
				self._running, self._connected  = [False, False]
				self._serverDisconnect()
				
	def _serverDisconnect(self, match=False):
		""" Disconnect from the IRC server and stop threads """
		logging.info('Disconnecting...')
		# clear channels, stop listening
		self.channels, self._connected, self._authed = [{}, False, False]
		try:
			self._stopThreads() # let threads finish
			#time.sleep(3) # give the internet a few seconds
			self._ircsock.shutdown(socket.SHUT_RDWR) # send shutdown event
		except Exception as e:
			logging.exception(e)
		finally:
			self._ircsock.close() # close socket
			logging.info("Socket Closed!")
	
	
	def _stopThreads(self):
		""" Closes and joins all the threadpools, then creates new pools """
		logging.info('Stopping threads...')
		try:
			# close and join thinkpool (should be child of listener thread)
			self._thinkpool.close();self._thinkpool.join()
			# create new pool
			self._thinkpool = Pool(self.maxthreads)
			logging.debug('Think pool cleared')
		except Exception as e:
			logging.exception(e)
		
		try:
			# join listener thread
			self._listenThread.join()
			logging.debug('Listen Thread joined')
		except Exception as e:
			logging.exception(e)
		
		logging.info('Threads (should be) stopped!')
	
	
	def _waitForShutdown(self):
		"""
		'Blocking' loop used to keep the program running
		(since everything is threaded)
		"""
		logging.info('Blocking loop started...')
		while self._running:
			try: 
				time.sleep(1) # be nice to cpu
			# if something fishy happens
			except Exception as e:
				self._serverDisconnect() # close connection
				self._running = False # stop the loop
				logging.exception(e)
	
	
################################################################################
	
	def _auth(self, nick):
		""" Login to the IRC server """
		logging.info('Authenticating bot with server...')
		self._send( # Todo: Make the IRC namespace accessible
		    "USER %s %s %s :This bot is a \
		    result of open-source development." % (nick, nick, nick)
		    )
		self.setNick(nick) # set nickname
		if self.pswrd:
		    # identify with nickserv if a password is provided
			self._identifyNick(self.pswrd)
			count = 0
			logging.info('Waiting for Nickserv'),
			while not self._authed: # wait for Nickserv or timeout (60 sec)
				time.sleep(1)
				count+=1
				if count > 60:
					logging.warn('Nickserv fail!'); break
	
	def _joinChanlist(self):
		""" Join all the channels in self.channellist """
		for chan in self.channellist:
			self.joinChannel(chan)
	
	def _sniffLine(self, line):
		""" 
		Searches the line for anything relevent
		executes the function for the match 
		"""
		logging.debug("<< %s" % line)
		for item in self._serverRe:
			match = self._serverRe[item]['cregex'].search(line)
			if match: 
				logging.info("< %s" % line)
				self._serverRe[item]['function'](match)
	
	def _sniffMessage(self, match):
		""" 
		Search PRIVMESG/NOTICE for a command 
		executes the function for the match
		"""
		for item in self.commands:
			cmatch = self.commands[item]['cregex'].search(match.group(4))
			if cmatch:
				channel = match.group(3)
				if channel == match.group(1): 
				    channel = self.botnick
				self.commands[item]['function'](channel, match.group(1), cmatch)
			
################################################################################
	
	def loadCommands(self, commands):
		"""
		Loads a dict as self.commands and compiles regex (overwrites all)
		"""
		self.commands = commands
		self._thinkpool.map(self._compileCommandRe, self.commands)
	
	def addCommand(self, name, regex, funct):
		""" 
		Add a command to the self.commands dict 
		(overwrites commands with the same <name>)
		"""
		self.commands[name] = {
		        'function':funct, 'regex':regex, 'cregex': re.compile(regex)
		        }
	
	def removeCommand(self, name):
		""" Remove <name> command from the self.commands dict """
		del self.commands[name]
	
	def shutdown(self, message="I'll be back..."):
		""" Shutdown the bot with [message="I'll be back..."] """
		self.quit(message) # send quit message
		time.sleep(3) # give the internet a few seconds
		self._running = False # stop the bots 'blocking loop'
		self._serverDisconnect() # close connection
	
	def start(self, loop=True):
		""" Start the bot """
		self._compileCommands() # compile all the irc/commands regex
		self._serverConnect() # setup connection
		self._auth(self.botnick) # send auth
		if not self._authed:
		    raise RuntimeError("not authenticated")
		self._joinChanlist() # Join channels
		if loop: # Start "blocking" loop
		    self._waitForShutdown()
