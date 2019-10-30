import discord
import asyncio
import json
import re
import datetime
import pymysql


import settings

DEBUG = True

TRIGGER="@"

ADMINROLE=583043410693324801

YESEMOJI='\U00002705'
NOEMOJI='\U0000274C'

RAIDSTART="20:30"
RAIDEND="23:30"
EVENTCHANNEL=639111210528407573

print("Connecting to Mysql %s" % settings.DBNAME)
db = pymysql.connect(settings.DBHOST,settings.DBUSER,settings.DBPASS,settings.DBNAME)
cursor = db.cursor()

ROLES = ['tank','healer','physical','caster']
CLASSES= ['warrior','druid','priest','paladin','mage','warlock','hunter','rogue']

#Todo: !remindme, event reminders

class dClient(discord.Client):

	# Helper Functions
	async def is_mod(self,user):
		for role in user.roles:
			if role.id == ADMINROLE:
				return True
		return False

	async def get_events(self):
		try:
			cursor.execute("SELECT id,name,description,date,length,discord_id from events where active=True order by date ASC")
			data = cursor.fetchall()
		except Exception as e:
			print("Error getting events")
			print(e)
			return False

		for event in data:
			self.eventlist[event[0]] = {
				'id': event[0],
				'name': event[1],
				'desc': event[2],
				'date': event[3],
				'length': event[4],
				'discord_id': event[5],
				'attending': [],
				'declined': []
			}
			try:
				cursor.execute("SELECT discord_id,joined,accepted from eventmembers where event_id = %s order by joined ASC", (event[0],))
				data = cursor.fetchone()
				while data:
					if data[2]:
						self.eventlist[event[0]]['attending'].append(int(data[0]))
					else:
						self.eventlist[event[0]]['declined'].append(int(data[0]))
					data = cursor.fetchone()
			except Exception as e:
				print("Error getting event members")
				print(e)
				return False

			if event[5]:
				self.eventmap[event[5]] = event[0]

		return True

	async def update_event_posting(self,message_id):
		channel = self.get_channel(EVENTCHANNEL)
		message = await channel.fetch_message(message_id)
		if message:
			event = self.eventmap.get(message_id,False)
			if event:
				event = self.eventlist.get(event,False)
				if event:
					msg = await self.format_event(event)
					await message.edit(content=msg)
					return True
		return False

	async def add_event_member(self,user_id,message_id,attending=True):
		print(attending)
		member = self.memberlist.get(user_id,False)
		if not member:
			return False

		event_id = self.eventmap.get(message_id,False)
		if event_id:
			event = self.eventlist.get(event_id,False)
			if (user_id in self.eventlist[event_id]['attending'] and not attending) or (user_id in self.eventlist[event_id]['declined'] and attending):
				await self.remove_event_member(user_id,message_id,not attending)
			if not user_id in self.eventlist[event_id]['attending'] and not user_id in self.eventlist[event_id]['declined']:
				try:
					cursor.execute("INSERT INTO eventmembers(event_id,discord_id,accepted) VALUES (%s, %s, %s)", (event_id,user_id,attending))
					db.commit()
					if attending:
						self.eventlist[event_id]['attending'].append(user_id)
					else:
						self.eventlist[event_id]['declined'].append(user_id)
					await self.update_event_posting(message_id)

				except Exception as e:
					print("Database error on eventmember creation")
					print(e)
					db.rollback()
					return False
		return True

	async def remove_event_member(self,user_id,message_id,add=True):
		member = self.memberlist.get(user_id,False)
		if not member:
			return False

		event_id = self.eventmap.get(message_id,False)
		if event_id:
			event = self.eventlist.get(event_id,False)
			if (user_id in self.eventlist[event_id]['attending'] and add) or (user_id in self.eventlist[event_id]['declined'] and not add):
				try:
					cursor.execute("DELETE FROM eventmembers WHERE event_id = %s and discord_id = %s", (event_id,user_id))
					db.commit()
					if user_id in self.eventlist[event_id]['attending']:
						self.eventlist[event_id]['attending'].remove(user_id)
					if user_id in self.eventlist[event_id]['declined']:
						self.eventlist[event_id]['declined'].remove(user_id)
					await self.update_event_posting(message_id)
				except Exception as e:
					print("Database error on eventmember removal")
					print(e)
					db.rollback()
					return False
		return True

	async def get_members(self):
		try:
			cursor.execute("SELECT users.id, users.name, users.discord_id, users.discord_name, users.battletag, characters.name, characters.class, characters.role from users inner join characters on users.discord_id = characters.discord_id")
			data = cursor.fetchall()
		except Exception as e:
			print(e)
			return False

		for member in data:
			self.memberlist[member[2]] = {
				'name': member[1],
				'discord_id': int(member[2]),
				'discord_name': member[3],
				'battletag': member[4],
				'charname': member[5],
				'charclass': member[6],
				'charrole': member[7]
			}
		return True

	async def format_event(self,event,full=False):
		if isinstance(event['date'],datetime.datetime):
			start = event['date']
		else:
			start = datetime.datetime.strptime(event['date'],'%Y-%m-%d %H:%M')
		end = start + datetime.timedelta(hours=event['length'])
		roles = {
			'physical' : [],
			'caster' : [],
			'healer' : [],
			'tank' : []
		}
		declined = []
		nrlist = []

		for key in self.memberlist.keys():
			if self.memberlist[key]['discord_id'] in event['attending']:
                	        roles[self.memberlist[key]['charrole']].append(self.memberlist[key]['name'])
			elif self.memberlist[key]['discord_id'] in event['declined']:
	                        declined.append(self.memberlist[key]['name'])
			else:
				nrlist.append(self.memberlist[key]['name'])

		noresponse = ''
		if full:
			noresponse = '\n\n**No Response - %s**\n%s' % (
				len(nrlist),
                                ', '.join(nrlist) if len(nrlist) else "None")

		return ">>> **%s - %s**\n%s - %s EST\n%s hours\n\n%s\n\n**Tanks - %s**\n%s\n\n**Healers - %s**\n%s\n\n**Physical Dps - %s**\n%s\n\n**Caster Dps - %s**\n%s\n\n**Declined - %s**\n%s%s" % (
				event['name'],
				event['id'],
				start.strftime("%A %B %d at %H:%M"),
				end.strftime("%H:%M"),
				event['length'],
				event['desc'],
				len(roles['tank']),
				', '.join(roles['tank']) if len(roles['tank']) else "None",
				len(roles['healer']),
				', '.join(roles['healer']) if len(roles['healer']) else "None",
				len(roles['physical']),
				', '.join(roles['physical']) if len(roles['physical']) else "None",
				len(roles['caster']),
				', '.join(roles['caster']) if len(roles['caster']) else "None",
				len(declined),
				', '.join(declined) if len(declined) else "None",
				noresponse)

	async def channel_cleanup(self):
		channel = self.get_channel(EVENTCHANNEL)
		counter = 0
		expired = 0
		async for message in channel.history(limit=500):
			if message.author != client.user:
				await message.delete()
				counter += 1
			else:
				if message.id not in self.eventmap.keys():
					await message.delete()
					expired +=1
		return (counter, expired)
	# Loops
	async def on_ready(self):
		print("Logged in as %s" % self.user)
		print("Loading event list")
		await self.get_events()
		print("%d events loaded" % len(self.eventlist))
		print("Loading member list")
		await self.get_members()
		print("%d members loaded" % len(self.memberlist))
		deleted, expired = await self.channel_cleanup()
		if deleted:
			print("Deleting %d messages by other users in the channel" % deleted)
		if expired:
			print("Deleting %d messages that no longer exist" % expired)

	async def server_list(self):
		await self.wait_until_ready()
		while not self.is_closed():
			print("Current servers:")
			for server in self.guilds:
				print("\t%s" % server.name)
			await asyncio.sleep(600)

	async def event_manager(self):
		await self.wait_until_ready()
		await asyncio.sleep(10)
		while not self.is_closed():
			print("Checking active events")
			if not len(self.eventlist):
				await self.get_events()
			for event in self.eventlist:
				fevent= await self.format_event(event)
				if not event.get('discord_id',False):
					print("No Discord message id")
			await asyncio.sleep(30)


	# Custom function rules
	async def reply(self,command,message,string):
		cmd = self.commands[command].get('alias',command)
		return self.commands[cmd].get('reply',False)

	async def modhelp(self,command,message,string):
		helplist = ''
		for key in self.commands.keys():
			if self.commands[key]['mod'] and not self.commands[key].get('alias',False):
				helplist = "%s\n%s - %s" % (helplist,key,self.commands[key]['description']) 
		return "```\nModerator Help\n\nUse %shelp [command] to get more info about specific commands.\n\nModerator Commands%s```" % (TRIGGER,helplist)

	async def help(self,command,message,string):
		string = string.lower()
		p = re.compile(r'(?P<command>[\w\d]+).*')
		m = p.search(string)
		if not m:
			helplist = ''
			for key in self.commands.keys():
				if not self.commands[key]['mod'] and not self.commands[key].get('alias',False):
					helplist = "%s\n%s - %s" % (helplist,key,self.commands[key]['description']) 
			return "```\nHelp\n\nUse %shelp [command] to get more info about specific commands.\n\nCommands%s```" % (TRIGGER,helplist)
		command = self.commands.get(m.group('command'),False)
		if not command or (command['mod'] and not await self.is_mod(message.author)):
			return "Command %s not found." % m.group('command')
		return "```\n%s\n%s\n\n%s```" % (m.group('command'),
							self.commands[m.group('command')].get('description',''),
							self.commands[m.group('command')].get('help',''))

	async def list_members(self,command,message,string):
		await self.get_members()
		msg = '```Character Name       Class        Role'
		for key in self.memberlist.keys():
			msg = "%s\n%s %s %s" % (msg,self.memberlist[key]['charname'].ljust(20), self.memberlist[key]['charclass'].ljust(12).capitalize(), self.memberlist[key]['charrole'].capitalize())
		return '%s```' % msg


	async def list_events(self,command,message,string):
		msg=''
		for key,event in self.eventlist.items():
			msg = "%s%s %s %s %s hours\n" % (msg,event['id'],event['name'],event['date'].strftime("%A %B %d at %H:%M"),event['length'])
		return "```%s```" % msg

	async def get_event(self,command,message,string):
		try:
			event = self.eventlist[int(string)]
		except Exception as e:
			print(e)
			return "Could not get event. Check %shelp getevent" % TRIGGER

		msg = await self.format_event(event, full=True)

		return msg

	async def refresh_event(self,command,message,string):
		try:
			event = self.eventlist[int(string)]
		except Exception as e:
			print(e)
			return "Could not get event. Check %shelp refreshevent" % TRIGGER

		msg = await self.format_event(event)

		oldid = event['discord_id']
		channel = self.get_channel(EVENTCHANNEL)
		message = await channel.send(msg)


		try:
			cursor.execute("UPDATE events SET discord_id = %s where id = %s", (message.id,int(string)))
			try:
				oldmessage = await channel.fetch_message(event['discord_id'])
				await oldmessage.delete()
			except:
				pass
			self.eventlist[event['id']]['discord_id'] = message.id
			self.eventmap[message.id] = event['id']
			del(self.eventmap[oldid])
			db.commit()
		except Exception as e:
			print(e)
			await message.delete()
			db.rollback()
			return "Database error on event creation."
		try:
			await self.get_events()
		except Exception as e:
			print(e)
			return "Error loading event list"

		await message.add_reaction(YESEMOJI)
		await message.add_reaction(NOEMOJI)

		return ''


	async def add_user(self,command,message,string):
		if not message.mentions or len(message.mentions) > 1:
			return 'Invalid discord ID see %shelp addmember' % TRIGGER


		#p = re.compile(r'(?P<name>\S+) (?P<discord>\<@\d+\>) (?P<battletag>[\w#]+) (?P<charname>\S+) (?P<class>\w+) (?P<role>\w+).*')
		p = re.compile(r'(?P<name>\S+) (?P<discord>\<@\d+\>) (?P<charname>\S+) (?P<class>\w+) (?P<role>\w+).*')
		m = p.search(string)
		if not m:
			return 'Error parsing command values. Check %shelp addmember' % TRIGGER

		name = m.group('name')
		mentions = message.mentions[0]
		discord_id = message.mentions[0].id
		discord_name = message.mentions[0].display_name
		#battletag = m.group('battletag')
		battletag = "None"
		charname = m.group('charname')
		cclass = m.group('class').lower()
		role = m.group('role').lower()

		if cclass not in CLASSES:
			return "Invalid class. See %shelp adduser" % TRIGGER
		if role not in ROLES:
			return "Invalid role. See %shelp adduser" % TRIGGER

		try:
			cursor.execute("SELECT * from users where discord_id=%s", (discord_id,))
			data = cursor.fetchone()
		except Exception as e:
			print(e)
			return "Database error on lookup"


		if data:
			return "Discord user already exists, try %sgetmember" % TRIGGER
		try:
			cursor.execute("INSERT INTO users(name,discord_name,discord_id,battletag) VALUES (%s, %s, %s, %s)", (name,discord_name,discord_id,battletag))
			cursor.execute("INSERT INTO `characters`(name,class,role,discord_id) VALUES (%s, %s, %s, %s)", (charname, cclass, role,discord_id))
			db.commit()
		except Exception as e:
			print(e)
			db.rollback()
			return "Database error on creation"

		await self.get_members()

		return "Done"

	async def get_user(self,command,message,string):
		discord_id = False
		if message.mentions and len(message.mentions) == 1:
			discord_id = message.mentions[0].id
		else:
			p = re.compile(r'(?P<name>\S+).*')
			m = p.search(string)
			if not m:
				return 'Error parsing command values. Check %shelp getmember' % TRIGGER
			name = m.group('name')

		try:
			if discord_id:
				cursor.execute("SELECT users.id, users.name, users.discord_name, users.battletag, characters.name, characters.class, characters.role from users inner join characters on users.discord_id = characters.discord_id where users.discord_id=%s", (discord_id,))
			else:
				cursor.execute("SELECT users.id, users.name, users.discord_name, users.battletag, characters.name, characters.class, characters.role from users inner join characters on users.discord_id = characters.discord_id where users.name=%s", (name,))
			data = cursor.fetchone()
		except Exception as e:
			print(e)
			return "Database error looking up character"
		if data:
			return "```\nName:%s\nDiscord Name: %s\nBattletag:%s\n\nCharacter Name:%s\nClass:%s\nRole:%s```" % (data[1],data[2],data[3],data[4],data[5],data[6])

		return "No matching user found."

	async def add_event(self,command,message,string):
		p = re.compile(r'"(?P<name>.+)" (?P<date>[\w\d:\-/]+) (?P<length>[\d\.]+) (?P<desc>.*)')
		m = p.search(string)
		if not m:
			return 'Error parsing command values. Check %shelp addevent' % TRIGGER

		name = m.group('name')
		date = m.group('date')
		length = float(m.group('length'))
		desc = m.group('desc')

		days = {
			'monday': 0,
			'tuesday': 1,
			'wednesday': 2,
			'thursday': 3,
			'friday': 4,
			'saturday': 5,
			'sunday': 6

		}

		if date.lower() in days.keys():
			day = days.get(date.lower())
			now = datetime.datetime.now()
			start = now + datetime.timedelta( (day-now.weekday()) % 7 )
			start = start.replace(hour=int(RAIDSTART.split(':')[0]),minute=int(RAIDSTART.split(':')[1]),second = 0,microsecond = 0, tzinfo=None)
		else:
			try:
				p = re.compile(r'(?P<day>\d+)/(?P<month>\d+).*\-(?P<hour>\d+):(?P<minute>\d+).*')
				m = p.search(string)

				if not m:
					return "Could not parse start date. Check %shelp adddevent" % TRIGGER

				day=int(m.group('day'))
				month=int(m.group('month'))
				hour=int(m.group('hour'))
				minute=int(m.group('minute'))
				year=datetime.datetime.now().year

				start = datetime.datetime(year=year,day=day,month=month,hour=hour,minute=minute,tzinfo=None)
				if start < datetime.datetime.now():
					start = start.replace(year=year+1)

			except Exception as e:
				print(e)
				return "Could not parse start date. Check %shelp adddevent" % TRIGGER

		try:
			end = start + datetime.timedelta(hours=length)
		except Exception as e:
			print(e)
			return "Could not parse event length. Check %shelp adddevent" % TRIGGER

		event = {
			'name': name,
			'date': start.isoformat(sep=' ',timespec='minutes'),
			'desc': desc,
			'length': length,
			'attending': []
		}

		fevent = await self.format_event(event)
		channel = self.get_channel(EVENTCHANNEL)
		message = await channel.send(fevent)


		try:
			cursor.execute("INSERT INTO events(name,date,description,length,discord_id) VALUES (%s, %s, %s, %s, %s)", (name, start.isoformat(sep=' ',timespec='minutes'), desc, length, str(message.id)))
			db.commit()
		except Exception as e:
			print(e)
			await message.delete()
			db.rollback()
			return "Database error on event creation."
		try:
			await self.get_events()
		except Exception as e:
			print(e)
			return "Error loading event list"

		await message.add_reaction(YESEMOJI)
		await message.add_reaction(NOEMOJI)
		return "Event added!"

	async def fix_channels(self,command,message,string):
		for channel in message.guild.channels:
			if '_' in channel.name:
				await message.channel.send("Renaming %s to %s" % (channel.name, channel.name.replace('_','\u2009')))
				await channel.edit(name=channel.name.replace('_','\u2009'))
		return False

	# Reaction handler

	async def reaction_handler(self,reactionEvent,add=True):
		if reactionEvent.channel_id == EVENTCHANNEL and reactionEvent.message_id in self.eventmap.keys():
			channel = self.get_channel(EVENTCHANNEL)
			message = await channel.fetch_message(reactionEvent.message_id)
			if reactionEvent.user_id in self.memberlist.keys():
				if reactionEvent.emoji.name == YESEMOJI or reactionEvent.emoji.name == NOEMOJI:
					if add:
						res = await self.add_event_member(reactionEvent.user_id,reactionEvent.message_id,True if reactionEvent.emoji.name == YESEMOJI else False)
					else:
						res = await self.remove_event_member(reactionEvent.user_id,reactionEvent.message_id,True if reactionEvent.emoji.name == YESEMOJI else False)

			event = self.eventmap.get(reactionEvent.message_id,False)
			if not event:
				return

			event = self.eventlist.get(event,False)
			if not event:
				return

			for reaction in message.reactions:
				if reaction.emoji == YESEMOJI:
					async for user in reaction.users():
						if user != self.user and user.id not in event['attending']:
							await reaction.remove(user)
				if reaction.emoji == NOEMOJI:
					async for user in reaction.users():
						if user != self.user and user.id not in event['declined']:
							await reaction.remove(user)
			await message.add_reaction(YESEMOJI)
			await message.add_reaction(NOEMOJI)

	async def on_raw_reaction_add(self,reactionEvent):
		await self.reaction_handler(reactionEvent,True)

	async def on_raw_reaction_remove(self,reactionEvent):
		await self.reaction_handler(reactionEvent,False)

	# Main message handler
	async def on_message(self,message):
		if message.author != self.user:
			if message.channel.id == EVENTCHANNEL:
				await message.delete()
				return
			if message.content.startswith(TRIGGER):
				textcommand = re.sub(r'%s(\w+).*' % TRIGGER, '\\1', message.content).lower()
				command = self.commands.get(textcommand,False)
				if command:
					if command['mod'] and not await self.is_mod(message.author):
						return
					if command.get('alias',False):
						cmd = commands[command['alias']]['function']
					else:
						cmd = command['function']

					msg = await cmd(self,textcommand,message,message.content.replace('%s%s ' % (TRIGGER,textcommand),'').replace('%s%s' % (TRIGGER,textcommand),''))
					if msg:
						#print(msg)
						await message.channel.send(msg)
				else:
					print("No command found")

	eventlist = {}
	memberlist = {}
	eventmap = {}

	commands = {
		'listevents': {
			'mod' : True,
			'function': list_events,
			'reply': '',
			'description': 'Display a list of all of the upcoming events.',
			'help' : '%slistevents' % TRIGGER

		},
		'getevent': {
			'mod' : True,
			'function': get_event,
			'reply': '',
			'description': 'Display details for a specific event.',
			'help' : '%sgetevent <id>\n\nID is the numeric value given in %slistevents.' % (TRIGGER,TRIGGER)

		},
		'refreshevent': {
			'mod' : True,
			'function': refresh_event,
			'reply': '',
			'description': 'Repost the event and delete the original post.',
			'help' : '%srefreshevent <id>\n\nID is the numeric value given in %slistevents.\nThis can be used when the reactions break on an event.' % (TRIGGER,TRIGGER)

		},
		'addmember': {
			'mod' : True,
			'function': add_user,
			'reply': '',
			'description': 'Add a member to the guild list',
#			'help' : '%saddmember <Name> <@discord> <battletag> <charactername> <class> <role>\n\nName is just a nickname for identification\nPing their discord to link it\nBattletag can be set to anything if unknown\nClasses: Priest, Warlock, Mage, Hunter, Warrior, Paladin, Rogue, Druid\nRoles: Tank, Healer, Physical, Caster\n\nEx - %saddmember Verris @verris Verris#1318 Verris Priest Healer\n' % (TRIGGER,TRIGGER)
			'help' : '%saddmember <Name> <@discord> <charactername> <class> <role>\n\nName is just a nickname for identification\nPing their discord to link it\nClasses: Priest, Warlock, Mage, Hunter, Warrior, Paladin, Rogue, Druid\nRoles: Tank, Healer, Physical, Caster\n\nEx - %saddmember Verris @verris Verris Priest Healer\n' % (TRIGGER,TRIGGER)

		},
		'getmember': {
			'mod' : True,
			'function': get_user,
			'reply': '',
			'description': 'Get a member\'s info from the guild list',
			'help' : '%saddmember <Name|@discord>' % TRIGGER

		},
		'listmembers': {
			'mod' : True,
			'function': list_members,
			'reply': '',
			'description': 'List all of the current raiding members.',
			'help' : '%slistmembers' % TRIGGER

		},
		'addevent': {
			'mod' : True,
			'function': add_event,
			'reply': '',
			'description': 'Add an event to the event list',
			'help' : '%saddevent "<name>" <date> <length> <description>\n\nEvent name should be in double quotes.\nDate can be a weekday, which it will pick the next of, at the scheduled raid time, or date time in the format of day/month-hour:minute\nLength is in hours\n\nEx - %saddevent "Molten Core" Sunday 3 We\'re going to clear MC this time\n     %saddevent "BWL" 12/11-18:30 4.5 Starting on BWL early at 6:30 this time' % (TRIGGER,TRIGGER,TRIGGER)

		},
		'fixchannels': {
			'mod' : True,
			'function': fix_channels,
			'reply': '',
			'description': 'Fix the channel list',
			'help' : '%sfixchannels\n\nAttempts to replace all _ character with a thin space character in channel names.' % TRIGGER

		},
		'modping': {
			'mod' : True,
			'function': reply,
			'reply': 'Modpong',
			'description': 'Ping the bot with moderator permission.',
			'help' : '%smodping' % TRIGGER

		},
		'ping': {
			'mod' : False,
			'function': reply,
			'reply': 'Pong',
			'description': 'Ping the bot',
			'help' : '%sping' % TRIGGER

		},
		'help': {
			'mod' : False,
			'function': help,
			'description': 'List commands or get help with a specific command',
			'help' : '%shelp [command]\n\nEx - %shelp ping' % (TRIGGER,TRIGGER)

		},
		'modhelp': {
			'mod' : True,
			'function': modhelp,
			'description': 'List moderator commands',
			'help' : '%smodhelp' % TRIGGER

		},


	}




client = dClient()
client.loop.create_task(client.server_list())
#client.loop.create_task(client.event_manager())
client.run(settings.TOKEN)
db.close()
