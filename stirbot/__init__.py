#!/usr/bin python
import sys, time
import logging, logging.handlers
import re, socket
from multiprocessing.dummy import Pool, Process
from multiprocessing import cpu_count
import ssl

logging.basicConfig(format='[%(asctime)s](ircbot) %(message)s', datefmt="%Y-%m-%d %H:%M:%S", level=logging.DEBUG)
logger = logging.getLogger()
logger.addHandler(logging.handlers.RotatingFileHandler('ircbot.log', maxBytes=10**9, backupCount=5)) # makes 1Gb log files, 5 files max

class Bot(object):
	""" IRC Bot """
	def __init__(self, server="irc.freenode.net", port=7000, botnick="testbot", pswrd=False, channelist=["#slotbot"], maxthreads=cpu_count()*cpu_count()):
		"""
		self.server = IRC server address
		self.port = IRC server port
		self.botnick = Nickname to be used by bot
		self.pswrd = Nickserv password
		self.channellist = List of channels to join when bot starts
		self.maxthreads  = Number of threads to have waiting per pool
		
		# send a message
		self.sendMessage = lambda target, message: self._send("PRIVMSG %s :%s" % (target, message))
		
		# send a notice
		self.sendNotice = lambda target, message: self._send("NOTICE %s :%s" % (target, message)) 
		
		# check the acc level of a nick
		self.checkACC = lambda nick: self._send("NICKSERV ACC %s" % nick) 
		
		# join a channel
		self.joinChannel = lambda channel: self._send("JOIN %s" % channel) 
		
		# leave a channel
		self.partChannel = lambda channel: self._send("PART %s" % channel) 
		
		# change nickname
		self.setNick = lambda nick: self._send("NICK %s" % nick)
		
		# set away message 
		self.setAway = lambda message="I'll be back!": self._send("AWAY :%s" % message) 
		
		# come back from away
		self.unsetAway = lambda x='': self._send("AWAY ") 
		
		# set mode for a nick
		self.setMode = lambda nick, flags: self._send("MODE %s +%s" % (nick, flags)) 
		
		# unset mode for a nick
		self.unsetMode = lambda nick, flags: self._send("MODE %s -%s" % (nick, flags)) 
		
		# change channel topic
		self.setChannelTopic = lambda channel, topic: self._send("TOPIC %s :%s" % (channel, topic)) 
		
		# kick a user
		self.kickUser = lambda channel, nick, message: self._send("KICK %s %s :%s" % (channel, nick, message)) 
		
		# send quit message
		self.quit = lambda message="I'll be back!": self._send("QUIT :%s" % message) 
		
		self.channels = a dict of channels the bot is active in
		- each channel has a dict of the users in that channel with the value of the users modeset/acclevel
		- {'#channelName': {'topic': 'Channel Topic', 'users':{'name': 'o,v or 0-3'}},,,}
		
		self.commands = user defined dict of regex to look for in privmsgs
		- { 'quit':{'function': quit, 'regex': r'!quit'},,, }
		"""
		
		# Set attributes
		self.server, self.port, self.botnick, self.pswrd, self.channellist, self.maxthreads = [server, port, botnick, pswrd, channelist, maxthreads]
		# There is no socket yet, so we are not connected or authenticated, but we are running
		self._ircsock, self._connected, self._authed, self._running = [None, False, False, True] 
		# Set up threads
		self._thinkpool, self._listenThread = [Pool(self.maxthreads), Process(name='Listener', target=self._listen)]
		self._listenThread.daemon = True
		# IRC server command lambdas, to save trees...
		self._pong = lambda match: self._send("PONG :%s" % match.group(1))
		self._identifyNick = lambda pswrd: self._send("NICKSERV IDENTIFY %s" % (pswrd))
		#----------------
		self.sendMessage = lambda target, message: self._send("PRIVMSG %s :%s" % (target, message)) # send a message
		self.sendNotice = lambda target, message: self._send("NOTICE %s :%s" % (target, message)) # send a notice
		self.checkACC = lambda nick: self._send("NICKSERV ACC %s" % nick) # check the acc level of a nick
		self.joinChannel = lambda channel: self._send("JOIN %s" % channel) # join a channel
		self.partChannel = lambda channel: self._send("PART %s" % channel) # leave a channel
		self.setNick = lambda nick: self._send("NICK %s" % nick) # change nickname
		self.setAway = lambda message="I'll be back!": self._send("AWAY :%s" % message) # set away message
		self.unsetAway = lambda x='': self._send("AWAY ") # come back from away
		self.setMode = lambda nick, flags: self._send("MODE %s +%s" % (nick, flags)) # set mode for a nick
		self.unsetMode = lambda nick, flags: self._send("MODE %s -%s" % (nick, flags)) # unset mode for a nick
		self.setChannelTopic = lambda channel, topic: self._send("TOPIC %s :%s" % (channel, topic)) # change channel topic
		self.kickUser = lambda channel, nick, message: self._send("KICK %s %s :%s" % (channel, nick, message)) # kick a user
		self.quit = lambda message="I'll be back!": self._send("QUIT :%s" % message) # send quit message
		#----------------
		# IRC Server related compiled regex and functions ("things to listen for and do")
		self._serverRe = {
			'_Ping': {'function': self._pong, 				'regex': r'^PING :(.*)' },
			'_Privmsg':	{'function': self._sniffMessage, 	'regex': r'^:(.*)!~(.*) PRIVMSG (.*) :(.*)' },
			'_Notice': {'function': self._sniffMessage, 	'regex': r'^:(.*)!~(.*) NOTICE (.*) :(.*)' },
			'_ACC':	{'function': self._updateACC, 			'regex': r'^:.* NOTICE %s :(.+) ACC (\d)(.*)?' % self.botnick},
			'_Topic1': {'function': self._updateTopic, 		'regex': r'^:.* 332 %s (.*) :(.*)' % self.botnick},
			'_Topic2': {'function': self._updateTopic, 		'regex': r'^:.* TOPIC (.*) :(.*)'},
			'_Names': {'function': self._updateNames,		'regex': r'^:.* 353 %s . (.*) :(.*)' % self.botnick},
			'_Quit': {'function': self._somebodyQuit, 		'regex': r'^:(.*)!.* QUIT :'},
			'_Modeset':	{'function': self._modeSet,			'regex': r'^:.* MODE (.*) \+([A-Za-z]) (.*)'},
			'_Modeunset': {'function': self._modeUnset, 	'regex': r'^:.* MODE (.*) -([A-Za-z]) (.*)'},
			'_Join': {'function': self._joinedUser, 		'regex': r'^:(.*)!.* JOIN (.*)'},
			'_Part': {'function': self._removeUser,			'regex': r'^:(.*)!.* PART (.*) :.*'},
			'_Identify': {'function': self._identified,		'regex': r'^:NickServ!NickServ@services. NOTICE %s :You are now identified for.*' % self.botnick},
			'_Error': {'function': self._serverDisconnect,	'regex': r'^ERROR :Closing Link:.*'}
			}
			
		self.channels = self.commands = {}
		
	#########################################################################################################################################
	
	def _joinedUser(self, match):
		""" Fires when a user joins a channel"""
		if match.group(2) not in self.channels:
			self.channels.update({match.group(2):{}})
		if match.group(1) != self.botnick:
			self.addUser(match.group(2), match.group(1))
		
	def _somebodyQuit(self, match):
		""" Fires when a user quits"""
		for channel in self.channels.keys():
			for user in self.channels[channel].keys():
				if self.channels[channel][user].key() == match.group(1):
					del self.channels[channel][user]
		
	def _addUser(self, channel, name):
		""" Add a user to a channel in the CHANNELS dict"""
		self.channels[channel]['users'].update({name:''})
		
	def _removeUser(self, match):
		""" Remove a user from a channel in the CHANNELS dict"""
		if match.group(1) == self.botnick: del self.channels[match.group(2)]
		else: del self.channels[match.group(2)]['users'][match.group(1)]
	
	def _updateTopic(self, match):
		""" Update the topic for a channel in the CHANNELS dict"""
		if match.group(1) not in self.channels:	self.channels.update({match.group(1):{'topic':match.group(2)}})
		else: self.channels[match.group(1)]['topic'] = match.group(2)
		
	def _updateNames(self, match):
		""" Take names from a 353 and populate the CHANNELS dict"""
		channel, names = [match.group(1), match.group(2).split(' ')]
		if not 'users' in self.channels[channel]: self.channels[channel]['users'] = {}
		for name in names:
			if name[0] == '@': self.channels[channel]['users'].update({name[1:]:'o'})
			if name[0] == '+': self.channels[channel]['users'].update({name[1:]:'v'})
			if name[0] != '@' and name[0] != '+': self.channels[channel]['users'].update({name:''})
			
	def _updateACC(self, match):
		""" Attempts to update a users mode with an ACC level"""
		for channel in self.channels:
			for user in self.channels[channel]['users']:
				mode = self.channels[channel]['users']
				if 'o' not in mode  or  'v' not in mode  and  match.group(2) == user:
					if not mode  or  int(mode) < int(match.group(3)):
						self.channels[channel]['users'][user]['mode'] = match.group(3)
	
	def _modeSet(self, match):
		""" Adds mode flags to a user in the CHANNELS dict"""
		channel, mode, nick = [match.group(1), match.group(2), match.group(3)]
		for user in self.channels[channel]['users'].keys():
			if user == nick:
				oldModes, newModes = [self.channels[channel]['users'][user], mode]
				for flag in newModes:
					if flag not in oldModes:
						self.channels[channel]['users'][user] = self.channels[channel]['users'][user]+flag.lower()
	
	def _modeUnset(self, match):
		""" Removes mode flags from a user in the CHANNELS dict"""
		channel, mode, nick = [match.group(1), match.group(2), match.group(3)]
		for user in self.channels[channel]['users'].keys():
			if user == nick:
				for flag in mode.lower():
					self.channels[channel]['users'][user] = self.channels[channel]['users'][user].replace(flag,'')
					
	#-------------------
	def _compileServerRe(self, command):
		""" Compiles single server regex by cammand name"""
		self._serverRe[command]['cregex'] = re.compile(self._serverRe[command]['regex'])
	
	def _compileCommandRe(self, command):
		""" Compiles single command regex by cammand name"""
		self.commands[command]['cregex'] = re.compile(self.commands[command]['regex'])
	
	def _compileCommands(self):
		""" Uses the thread pool to compile all the commands regex"""
		self._thinkpool.map(self._compileServerRe, self._serverRe)
		self._thinkpool.map(self._compileCommandRe, self.commands)
	
	def _stopThreads(self):
		""" Closes and joins all the threadpools, then creates new pools"""
		logging.info('Stopping threads...')
		self._listenThread.join(5)
		# reset the thread incase we reboot (todo: add working reboot function)
		self._listenThread = Process(name='Listener', target=self._listen);self._listenThread.daemon = True
		self._thinkpool.close();self._thinkpool.join()
		self._thinkpool = Pool(self.maxthreads)
		logging.debug('Think pool cleared')
		logging.info('Threads stopped!')
	
	def _waitForShutdown(self):
		""" 'Blocking' loop used to keep the program running, since everything is threaded"""
		logging.info('Blocking loop started...')
		while self._running:
			try: time.sleep(3) # be nice to cpu
			except KeyboardInterrupt: self.shutdown() # make sure we close socket before closing program
	
	#########################################################################################################################################
	
	def _serverConnect(self):
		""" Create the connection to the IRC server"""
		logging.info("Connecting...")
		while not self._connected and self._running: # keep trying socket until connected, told to shutdown or unknown error
			try:
				sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # create socket
				sock.settimeout(360) # set timeout
				self._ircsock = ssl.wrap_socket(sock) # wrap socket in ssl
				self._ircsock.connect((self.server, self.port)) # connect
				self._connected = True
				logging.info("Apparently connected...")
				self._listenThread.start() # start listening thread
			except socket.error as e:
				logging.warn(e);time.sleep(5);logging.info("Trying socket again...")
			except Exception as e: raise e
				
	def _serverDisconnect(self, match=False):
		""" Disconnect from the IRC server and stop threads"""
		logging.info('Disconnecting...')
		self.channels = {} # clear channels
		self._connected = False # stop listening
		time.sleep(3) # give the internet a few seconds
		self._authed = False # allow reconnect?
		try:
			self._ircsock.shutdown(socket.SHUT_RDWR) # send shutdown event
			self._stopThreads() # let threads finish
			self._ircsock.close() # close socket
			logging.info("Socket Closed!")
		except Exception as e: logging.warn(e)
	
	def _send(self, message):
		""" Send the message to IRC server"""
		logging.info("> %s" % message)
		message = "%s\r\n" % message
		self._ircsock.send(message.encode("utf-8"))
		
	def _listen(self):
		""" Listen for messages from IRC server"""
		logging.info('Listening...')
		while self._connected:
			try:
				data = self._ircsock.recv(4096)
				data = data.strip(b'\r\n').decode("utf-8")
				self._thinkpool.map(self._sniffLine, data.splitlines())
			except Exception as e:
				raise e
		logging.info('No longer listening...')
	
	def _auth(self, nick):
		""" Login to the server"""
		logging.info('Authenticating bot with server...')
		self._send("USER %s %s %s :This bot is a result of open-source development." % (nick, nick, nick)) # Todo: Make the IRC namespace accessible
		self.setNick(nick) # set nickname
		if self.pswrd:
			self._identifyNick(self.pswrd) # identify with nickserv if a password is provided
			count = 0
			logging.info('Waiting for Nickserv'),
			while not self._authed: # wait for Nickserv or timeout (60 sec)
				time.sleep(1)
				count+=1
				if count > 60:
					logging.warn('Nickserv fail!'); break
	
	def _identified(self, match=False):
		""" Tells the bot it is authenticated with Nickserv"""
		self._authed = True
	
	def _joinChanlist(self):
		""" Join all the channels in self.channellist"""
		for chan in self.channellist:
			self.joinChannel(chan)
	
	def _sniffLine(self, line):
		""" Searches the line for anything relevent
		executes the function for the match"""
		logging.debug("<< %s" % line)
		for item in self._serverRe:
			match = self._serverRe[item]['cregex'].search(line)
			if match: 
				logging.info("< %s" % line)
				self._serverRe[item]['function'](match)
	
	def _sniffMessage(self, match):
		""" Search PRIVMESG/NOTICE for a command 
		execute the function for the match"""
		for item in self.commands:
			cmatch = self.commands[item]['cregex'].search(match.group(4))
			if cmatch:
				channel = match.group(3)
				if channel == match.group(1): channel = self.botnick # message is private; channel = bot nickname
				self.commands[item]['function'](channel, match.group(1), cmatch)
			
	#########################################################################################################################################
	
	def loadCommands(self, commands):
		""" Loads a dict as self.commands and compiles regex (overwrites all)"""
		self.commands = commands
		self._thinkpool.map(self._compileCommandRe, self.commands)
	
	def addCommand(self, name, regex, funct):
		""" Add a command to the self.commands dict (overwrites commands with the same <name>)"""
		self.commands[name] = {'function':funct, 'regex':regex, 'cregex': re.compile(regex)}
	
	def removeCommand(self, name):
		""" Remove <name> command from the self.commands dict"""
		del self.commands[name]
	
	def shutdown(self, message="I'll be back..."):
		""" Shutdown the bot with [message="I'll be back..."]"""
		self.quit(message) # send quit message
		self._serverDisconnect() # close connection
		self._running = False # stop the bots 'blocking loop'
	
	def start(self, loop=True):
		""" Start the bot"""
		self._compileCommands()
		self._serverConnect() # Setup connection
		self._auth(self.botnick) # send auth
		self._joinChanlist() # Join channels
		if loop: self._waitForShutdown() # Start "blocking" loop
