# stirbot
Simple Threaded IRC Bot

## Install:
`sudo python setup.py install`

## Usage:
```python
import stirbot

bot = stirbot.IRCServer(server="irc.freenode.net", botnick="stirbot", channelist=['#stirbot'])

# These functions get executed when their corresponding regex is found in a "PRIVMSG" or "NOTICE"
# The Bot passes the following arguments to the commands function (in this order):
# <channel> (or nick if 1-1 chat)
# <nick> of person that sent the message
# <hostname> of nick
# <reMatch> object found in the message
# If, for some reason, other args are required they SHOULD BE OPTIONAL, the bot expects exactly 4

def oneHund(chan, nick, host, match):
	bot.sendMessage(channel, "Because, %s, when I'm chillin here in %s, I keep it 100." % (nick, channel))

def hello(chan, nick, host, match):
	bot.sendMessage(channel, "Hello there %s!" % nick)

def echo(chan, nick, host, match):
	bot.sendMessage(channel, "%s" % match.group(1))

def quit(chan, nick, host, match):
	bot.quit()

# Here you can define: a dict of regex to search for in each "PRIVMSG" or "NOTICE" and the corresponding function to fire if the regex is found
# Note: if you try and define this dict before defining your command functions you will get an error 
commands = {
                '100': CommandHandle(r'(.*(why|Why).*%s.*|.*%s.*(why|Why).*)' % (bot.botnick, bot.botnick), oneHund),
                'quit': CommandHandle(r'^!quit', quit),
                'echo': CommandHandle(r'(.*)', echo),
                }

# You would then load the dict into the bot using the following method
# Note: 'loadCommands' will OVERWRITE the entire current dict that resides in 'Bot.commands'

bot.loadCommands(commands)

# Alternitvly you can add indivdual commands to the existing list using the 'addCommand' method
# Note: this will also 'update' a command if you use the same <name> argument as well as automagicly compile the regex

bot.addCommand('hello', r'.*hello.*|.*Hello.*|.*HELLO.*', hello) #<name><regex><function>
bot.removeCommand('echo') # remove the 'echo' commmand (is this fails or is removed then everything that is said is repeated)

# start the bot and start internal 'blocking' loop

bot() #THIS SHOULD BE THE END OF YOUR SCRIPT! (anything after this will be executed after the bot is shutdown)
