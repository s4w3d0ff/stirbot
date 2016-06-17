# stirbot
Simple Threaded IRC Bot

## Install:
`sudo python setup.py install`

## Usage:
```python
import stirbot

#>>> dir(stirbot)
#['Bot', 'Pool', 'Process', '__builtins__', '__doc__', '__file__', '__name__', '__package__', '__path__', 'cpu_count', 'logger', 'logging', 're', 'socket', 'ssl', 'sys', 'time']

bot = stirbot.Bot(server="irc.freenode.net", port=7000, botnick="stirbot", pswrd=False, channelist=['#stirbot'], maxthreads=16)
#>>> dir(bot)
#>>> ['__class__', '__delattr__', '__dict__', '__doc__', '__format__', '__getattribute__', '__hash__', '__init__', '__module__', '__new__', '__reduce__', '__reduce_ex__', '__repr__', '__setattr__', '__sizeof__', '__str__', '__subclasshook__', '__weakref__', '_addUser', '_auth', '_authed', '_compileCommandRe', '_compileCommands', '_compileServerRe', '_connected', '_identified', '_identifyNick', '_ircsock', '_joinChanlist', '_joinedUser', '_listen', '_listenThread', '_modeSet', '_modeUnset', '_pong', '_removeUser', '_running', '_send', '_serverConnect', '_serverDisconnect', '_serverRe', '_sniffLine', '_sniffMessage', '_somebodyQuit', '_stopThreads', '_thinkpool', '_updateACC', '_updateNames', '_updateTopic', '_waitForShutdown', 'addCommand', 'botnick', 'channellist', 'channels', 'checkACC', 'commands', 'joinChannel', 'kickUser', 'loadCommands', 'maxthreads', 'partChannel', 'port', 'pswrd', 'quit', 'removeCommand', 'sendMessage', 'sendNotice', 'server', 'setAway', 'setChannelTopic', 'setMode', 'setNick', 'shutdown', 'start', 'unsetAway', 'unsetMode']

# Note: If the bot.botnick attribute is changed you will need to call the bot._compileCommands() method 
# in order to make the appropriate changes to the server/commands regex
# ToDo: Fix the above note to be automagic

#---------------------------------------------------------------

# These functions get executed when their corresponding regex is found in a "PRIVMSG" or "NOTICE"
# The Bot passes the <channel> (or nick if 1-1 chat), <nick> of person that sent the message, and the <reMatch> object found in the message
# If, for some reason, other args are required they SHOULD BE OPTIONAL, the bot expects exactly 3

def oneHund(channel, nick, reMatch):
	bot.sendMessage(channel, "Because, %s, when I'm chillin here in %s, I keep it 100." % (nick, channel))

def hello(channel, nick, reMatch):
	bot.sendMessage(channel, "Hello there %s!" % nick)

def echo(channel, nick, reMatch):
	bot.sendMessage(channel, "%s" % reMatch.group(1))

def quit(channel, nick, reMatch):
	if channel in bot.ADMINS: # if the message is direct chat
		bot.shutdown()
	elif channel != nick:
		if '@' in bot.CHANNELS[channel]['users'][nick] or nick in bot.ADMINS:
			bot.shutdown() # Close connection to server with an optional closing [message] and stop the 'blocking' loop if it is running

# Here you can define: a dict of regex to search for in each "PRIVMSG" or "NOTICE" and the corresponding function to fire if the regex is found
# Note: if you try and define this dict before defining your command functions you will get an error 

commands = {
		'100':{'function': oneHund, 	'regex': r'(.*(why|Why).*%s.*|.*%s.*(why|Why).*)' % (bot.BOTNICK, bot.BOTNICK)},
		'quit':{'function': quit, 		'regex': r'!quit'},
		'echo':{'function': echo, 		'regex': r'(.*)'}
		}

# You would then load the dict into the bot using the following method
# Note: 'loadCommands' will OVERWRITE the entire current dict that resides in 'Bot.COMMANDS'

bot.loadCommands(commands)

# Alternitvly you can add indivdual commands to the existing list using the 'addCommand' method
# Note: this will also 'update' a command if you use the same <name> argument as well as automagicly compile the regex (bot.compileCommands() not required)

bot.addCommand('hello', r'.*hello.*|.*Hello.*|.*HELLO.*', hello) #<name><regex><function>
bot.removeCommand('echo') # remove the 'echo' commmand (is this fails or is removed then everything that is said is repeated)

# start the bot and start internal 'blocking' loop

bot.start() #THIS SHOULD BE THE END OF YOUR SCRIPT! (anything after this will be executed after the bot is shutdown)

###----------------------
# You could alternatively:
#
#bot.start(False) # starts the irc connection without a 'blocking' loop
#
# Execute some code here
#
# You can create you own personalized loop here then call 'bot.shutdown()' to stop bot
# or you can call: 
#bot.waitForShutdown() # starts the bots internal 'blocking' loop 
# (this then should be the last line in the file unless you want to execute somthing after the bot is shutdown)
# -----------------------
```
