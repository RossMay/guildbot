import discord
import asyncio
import json
import re
import datetime
import redis
import pickle

import settings

DEBUG = True

TRIGGER="@"
STATUS='Napping v2.0'

ROLES = {
	'admin' : 583043410693324801,
	'raider': 625944404276019220
}

SPECS = {
	640600006390186034: 'healer',
	640599870574559268: 'tank',
	640600049554030611: 'physical',
	640600233721724969: 'caster'
}

CLASSES = {
	583002026326097940: 'warrior',
	583001678446592004: 'druid',
	583001859325952030: 'priest',
	583001807547138052: 'paladin',
	583001280641892373: 'mage',
	583001990557073426: 'warlock',
	583001732330553424: 'hunter',
	583001882411139103: 'rogue',
	583001926866698240: 'shaman',
	640601798268157982: 'deathknight'
}

EMOJIS = {
	'yes': '\U00002705',
	'no': '\U0000274C',
	'delete': '\U0001F4A3',
	'repeat': '\U0001F501'
}

CHANNELS = {
	'event': 639111210528407573
}

SERVER = 582999149474218024

REDIS = {
	'host': '127.0.0.1'
}

RAIDSTART="20:30"
RAIDEND="23:30"
PINGMESSAGE="<@&%s> New raid posted, please sign up here!" % ROLES['raider']
NOTIFYMESSAGE="Please mark your availability in the <#%s> channel for: " % str(CHANNELS['event'])

ROLELIST = ['tank','healer','physical','caster']
CLASSLIST= ['warrior','druid','priest','paladin','mage','warlock','hunter','rogue', 'shaman', 'deathknight']
DEFAULTROLE = {
	'warrior': 'physical',
	'druid': 'healer',
	'priest': 'healer',
	'paladin': 'healer',
	'mage': 'caster',
	'warlock': 'caster',
	'hunter': 'physical',
	'rogue': 'physical',
	'shaman': 'healer',
	'deathknight': 'physical'
}


#Todo: !remindme, event reminders

class dClient(discord.Client):

	# Helper Functions

	# Save to Redis
	async def save(self):
		if self.membersloaded:
			db.set('memberlist',pickle.dumps(self.memberlist))
		if self.eventsloaded:
			db.set('eventlist',pickle.dumps(self.eventlist))

	# Sorting Function for member lists
	def sort_order(self,key):
		return key.lower()

	# Sorting for the member list
	def sort_member_list(self,key):
		return "%s%s" % (key[1].lower(),key[0].lower())

	# Check if a user has a given role ID
	async def has_role(self,user,role):
		if not isinstance(role,discord.Role):
			role = user.guild.get_role(role)
		if role in user.roles:
			return True
		return False

	# Check if the given user has the admin role
	async def is_mod(self,user):
		return await self.has_role(user,ROLES['admin'])

	# Get the event list from the storage backend
	async def get_events(self):
		el = db.get('eventlist')
		if el:
			self.eventlist = pickle.loads(el)
		self.eventmap = {}
		for key in self.eventlist.keys():
			if self.eventlist[key].get('discord_id', False):
				self.eventmap[self.eventlist[key]['discord_id']] = key
		self.eventsloaded=True

	# Get the next event ID
	async def get_next_event_id(self):
		highest = 0
		for key in self.eventlist.keys():
			if int(key) > highest:
				highest = int(key)
		return highest + 1

	# Get the list of people who have not responsed
	async def get_noresponse_list(self,id):
		event = self.eventlist.get(id,None)
		if not event:
			return []

		nrlist = []
		for key in self.memberlist.keys():
			if (not self.memberlist[key]['discord_id'] in event['attending']) and (not self.memberlist[key]['discord_id'] in event['declined']):
				nrlist.append(key)

		return nrlist


	# Update the discord posting for an event
	async def update_event_posting(self,message_id):
		channel = self.get_channel(CHANNELS['event'])
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

	# Add a response (Added emoji) to an event
	async def add_event_response(self,user_id,message_id,attending=True):
		event_id = self.eventmap.get(message_id,False)
		if event_id:
			event = self.eventlist.get(event_id,False)
			if (user_id in self.eventlist[event_id]['attending'] and not attending) or (user_id in self.eventlist[event_id]['declined'] and attending):
				await self.remove_event_response(user_id,message_id,not attending)
			if not user_id in self.eventlist[event_id]['attending'] and not user_id in self.eventlist[event_id]['declined']:
				if attending:
					self.eventlist[event_id]['attending'].append(user_id)
				else:
					self.eventlist[event_id]['declined'].append(user_id)
				await self.update_event_posting(message_id)
				await self.save()

	# Remove a response (Removed emoji) from an event
	async def remove_event_response(self,user_id,message_id,add=True):
		event_id = self.eventmap.get(message_id,False)
		if event_id:
			event = self.eventlist.get(event_id,False)
			if (user_id in self.eventlist[event_id]['attending'] and add) or (user_id in self.eventlist[event_id]['declined'] and not add):
				if user_id in self.eventlist[event_id]['attending']:
					self.eventlist[event_id]['attending'].remove(user_id)
				if user_id in self.eventlist[event_id]['declined']:
					self.eventlist[event_id]['declined'].remove(user_id)
				await self.update_event_posting(message_id)
				await self.save()

	# Load the member list from the storage backend
	async def get_members(self):
		ml = db.get('memberlist')
		if ml:
			self.memberlist = pickle.loads(ml)
		self.membersloaded = True

	# Format an event for posting
	async def format_event(self,event):
		start = datetime.datetime.strptime(event['date'],'%Y-%m-%d %H:%M')

		roles = {
			'physical' : [],
			'caster' : [],
			'healer' : [],
			'tank' : []
		}
		declined = []

		for key in self.memberlist.keys():
			if self.memberlist[key]['discord_id'] in event['attending']:
                	        roles[self.memberlist[key]['charrole']].append(self.memberlist[key]['name'])
			elif self.memberlist[key]['discord_id'] in event['declined']:
	                        declined.append(self.memberlist[key]['name'])

		for key in roles:
			roles[key].sort(key=self.sort_order)
		declined.sort(key=self.sort_order)

		noresponse = ''
		at = len(event['attending'])
		return ">>> **%s - #%s**\n%s EST\n%s\n\n%s\n\n**Tanks - %s**\n%s\n\n**Healers - %s**\n%s\n\n**Physical Dps - %s**\n%s\n\n**Caster Dps - %s**\n%s\n\n**Declined - %s**\n%s" % (
				event['name'],
				event['id'],
				start.strftime("%A %B %d at %H:%M"),
				'%s Attendee%s' % (at,'' if at == 1 else 's'),
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
				', '.join(declined) if len(declined) else "None")

	# Remove any posts in the event channel that are not made by the bot
	async def channel_cleanup(self):
		channel = self.get_channel(CHANNELS['event'])
		counter = 0
		async for message in channel.history(limit=200):
			if message.author != client.user:
				await message.delete()
				counter += 1
		return counter

	# Update the name of a user
	async def update_member_name(self,discord_id,name):
		if not discord_id in self.memberlist.keys():
			return False
		self.memberlist[discord_id]['name'] = name
		await self.save()
		return True

	# Update a member record
	async def update_member(self,id,name,m_class,m_spec,new_name=None,save=True):
		if new_name:
			name = new_name
		else:
			p = re.compile(r'.*\((?P<name>.+)\).*')
			m = p.search(name)
			if m:
				name = m.group('name')

		if not id in self.memberlist.keys():
			print(self.memberlist)
			self.memberlist[id] = {
				'discord_id': id,
				'name': name
			}

		if new_name:
			self.memberlist[id]['name'] = name

		self.memberlist[id]['charclass'] = m_class
		self.memberlist[id]['charrole'] = m_spec
		if save:
			await self.save()

	# Parse the member list and update all entries
	async def parse_members(self,server):
		if not self.membersloaded:
			return "Members not loaded yet"

		errors = ''
		start = len(self.memberlist)
		for member in server.members:
			if await self.has_role(member,server.get_role(ROLES['raider'])):
				m_class = None
				m_spec = None
				for role in CLASSES:
					if await self.has_role(member,role):
						m_class = CLASSES[role]
						break

				if not m_class:
					errors= '%s%s' % (errors,"User %s does not have a class assigned\n" % member)
					continue

				m_spec = DEFAULTROLE.get(m_class)
				for spec in SPECS:
					if await self.has_role(member,spec):
						m_spec = SPECS[spec]
						break

				await self.update_member(member.id,member.display_name,m_class,m_spec,save=False)
			else:
				if member.id in self.memberlist.keys():
					for event in self.eventlist:
						if member.id in self.eventlist[event]['attending']:
							self.eventlist[event]['attending'].remove(member.id)
						if member.id in self.eventlist[event]['declined']:
							self.eventlist[event]['declined'].remove(member.id)
					del self.memberlist[member.id]
		await self.save()
		if start != len(self.memberlist):
			print("Updated member list went from %s to %s" % (start, len(self.memberlist)))
		return errors if len(errors) else 'Done'


	# Parses the member list and adds members based on their roles
	async def parse_members_cmd(self,command,message,string):
		return await self.parse_members(message.guild)

	# Loop to parse the members on a regular basis
	async def server_list(self):
		await self.wait_until_ready()
		while not self.is_closed():
			await asyncio.sleep(600)
			await self.parse_members(client.get_guild(SERVER))

	# Runs once we connect to discord and are ready to go
	async def on_ready(self):
		print("Logged in as %s" % self.user)
		if STATUS:
			print("Setting status to %s" % STATUS)
			await self.change_presence(activity=discord.Game(STATUS))
		print("Loading event list")
		await self.get_events()
		print("%d events loaded" % len(self.eventlist))
		print("Loading member list")
		await self.get_members()
		print("%d members loaded" % len(self.memberlist))
		await self.parse_members(client.get_guild(SERVER))
		print("Parsed member list for any changes")
		deleted = await self.channel_cleanup()
		if deleted:
			print("Deleting %d messages by other users in the channel" % deleted)

	# Custom function rules

	# Simple reply function. Prints a preset response based on the reply value of the command dictionary.
	async def reply(self,command,message,string):
		cmd = self.commands[command].get('alias',command)
		return self.commands[cmd].get('reply',False)

	# Loop through and list the help commands for moderator only commands
	async def modhelp(self,command,message,string):
		helplist = ''
		for key in self.commands.keys():
			if self.commands[key]['mod'] and not self.commands[key].get('alias',False):
				helplist = "%s\n%s - %s" % (helplist,key,self.commands[key]['description']) 
		return "```\nModerator Help\n\nUse %shelp [command] to get more info about specific commands.\n\nModerator Commands%s```" % (TRIGGER,helplist)

	# Loop through the non moderator commands, or give the help command for a specific option
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
	# List all the members
	async def list_members(self,command,message,string):
		msg = '```%s Members\nName           Class     Role\n---------------------------------' % len(self.memberlist)
		members = []
		for key in self.memberlist.keys():
			members.append((self.memberlist[key]['name'],self.memberlist[key]['charclass'],self.memberlist[key]['charrole']))
		members.sort(key=self.sort_member_list)

		for mem in members:
			msg = "%s\n%s %s %s" % (msg,mem[0].ljust(14), mem[1].ljust(9).capitalize(), mem[2].capitalize())
		return '%s```' % msg

	# Manually change events by editing this code
	async def fix_events(self,command,message,string):
		return 'Done'

	# List all of the current events
	async def list_events(self,command,message,string):
		msg=''
		for key,event in self.eventlist.items():
			start = datetime.datetime.strptime(event['date'],'%Y-%m-%d %H:%M')
			msg = "%s%s %s %s %s Attending\n" % (msg,str(event['id']).rjust(3),event['name'].ljust(15), start.strftime("%b %d %H:%M"),str(len(event['attending'])).rjust(3))
		if not len(msg):
			msg = "No scheduled events."
		return "```%s```" % msg

	# Get details for a specific event
	async def get_event(self,command,message,string):
		try:
			event = self.eventlist[int(string)]
		except Exception as e:
			print(e)
			return "Could not get event. Check %shelp getevent" % TRIGGER

		msg = await self.format_event(event)

		return msg

	# Refresh an event posting, creating a new post.
	async def refresh_event(self,command,message,string):
		try:
			event = self.eventlist[int(string)]
		except Exception as e:
			print(e)
			return "Could not get event. Check %shelp refreshevent" % TRIGGER

		msg = await self.format_event(event)

		oldid = event['discord_id']
		channel = self.get_channel(CHANNELS['event'])
		message = await channel.send(msg)


		try:
			oldmessage = await channel.fetch_message(event['discord_id'])
			await oldmessage.delete()
		except:
			pass
		self.eventlist[event['id']]['discord_id'] = message.id
		self.eventmap[message.id] = event['id']
		del(self.eventmap[oldid])
		await self.save()

		await message.add_reaction(EMOJIS['yes'])
		await message.add_reaction(EMOJIS['no'])

		return "Event %s refreshed." % event['id']


	# Set a user's name
	async def set_name(self,command,message,string):
		discord_id = None
		p = re.compile(r'(?P<discord_id>\d+) (?P<newname>\S+).*')
		m = p.search(string)
		if not m:
			return 'Error parsing command values. Check %shelp setname' % TRIGGER

		discord_id = int(m.group('discord_id'))
		name = m.group('newname')

		if discord_id not in self.memberlist.keys():
			return "No matching user found for %s" % discord_id

		ret = await self.update_member_name(discord_id,name)
		if not ret:
			return "Error setting name"

		return "User updated"

	# Get info for a specific user
	async def _get_user(self,command,message,string):
		discord_id = False
		if message.mentions and len(message.mentions) == 1:
			member = self.memberlist.get(message.mentions[0].id,False)
		else:
			p = re.compile(r'(?P<name>\S+).*')
			m = p.search(string)
			if not m:
				return 'Error parsing command values. Check %shelp getmember' % TRIGGER

			name = m.group('name').lower()
			for key in self.memberlist.keys():
				if self.memberlist[key]['name'].lower() == name:
					member = self.memberlist[key]

		if member:
			return "```\nName: %s\nDiscord ID: %s\n\nClass: %s\nRole: %s```" % (member['name'],member['discord_id'],member['charclass'],member['charrole'])

		return "No matching user found."

	# Delete a specific event
	async def del_event(self,command,message,string):
		p = re.compile(r'(?P<id>[0-9]+)')
		m = p.search(string)
		if not m:
                	return 'Error parsing id value. Check %shelp delevent' % TRIGGER

		key = int(m.group('id'))
		if key not in self.eventlist.keys():
			return 'Could not find event %s' % event

		try:
			channel = self.get_channel(CHANNELS['event'])
			message = await channel.fetch_message(self.eventlist[key]['discord_id'])
			await message.delete()
		except Exception as e:
			print(e)
			print("Error removing event posting for event %s" % key)

		try:
			del self.eventmap[self.eventlist[key]['discord_id']]
		except Exception as e:
			pass

		del self.eventlist[key]
		await self.save()
		return "Event %s deleted." % key

	# Get a list of members who have not responded to an event
	async def noresponse_event(self,command,message,string):
		p = re.compile(r'(?P<id>[0-9]+)')
		m = p.search(string)
		if not m:
                	return 'Error parsing event id value. Check %shelp %s' % (TRIGGER, command)

		key = int(m.group('id'))
		if key not in self.eventlist.keys():
			return 'Could not find event %s' % key

		nrlist = await self.get_noresponse_list(key)

		if len(nrlist):
			nrlist.sort(key=lambda key: self.memberlist[key]['name'].lower())
			return "```%s people have not responded: %s```" % (len(nrlist),', '.join(self.memberlist[m]['name'] for m in nrlist))

		return "```No outstanding responses```"

	# Notify anyone who has not responsed
	async def noresponse_message(self,command,message,string):
		p = re.compile(r'(?P<id>[0-9]+) (?P<message>.+)')
		m = p.search(string)
		msg = ''
		if not m:
			p = re.compile(r'(?P<id>[0-9]+)')
			m = p.search(string)
			if not m:
                		return 'Error parsing event id value. Check %shelp %s' % (TRIGGER, command)
			msg = NOTIFYMESSAGE


		key = int(m.group('id'))
		if key not in self.eventlist.keys():
			return 'Could not find event %s' % key

		if not msg:
			msg = m.group('message')
		else:
			msg = "%s %s - %s" % (msg, self.eventlist[key]['name'],str(key))

		nrlist = await self.get_noresponse_list(key)

		if len(nrlist):
			for id in nrlist:
				await message.guild.get_member(id).send(msg)
			return "%s people have been notifed.\n>>> %s" % (len(nrlist),msg)

		return "There is nobody to notify."

	# Add a new event
	async def add_event(self,command,message,string):
		p = re.compile(r'"(?P<name>.+)" (?P<date>[\w\d:\-/]+) (?P<desc>.*)')
		m = p.search(string)
		if not m:
			return 'Error parsing command values. Check %shelp addevent' % TRIGGER

		name = m.group('name')
		date = m.group('date')
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

		id = await self.get_next_event_id()

		self.eventlist[id] = {
			'id': id,
			'name': name,
			'date': start.isoformat(sep=' ',timespec='minutes'),
			'desc': desc,
			'attending': [],
			'declined': []
		}

		fevent = await self.format_event(self.eventlist[id])
		channel = self.get_channel(CHANNELS['event'])
		await channel.send(PINGMESSAGE)
		message = await channel.send(fevent)

		self.eventlist[id]['discord_id'] = message.id
		self.eventmap[message.id] = id

		await message.add_reaction(EMOJIS['yes'])
		await message.add_reaction(EMOJIS['no'])
		await self.save()
		return "Event #%s added!" % id

	# Replace any _ with a spcae in channel names
	async def fix_channels(self,command,message,string):
		for channel in message.guild.channels:
			if '_' in channel.name:
				await message.channel.send("Renaming %s to %s" % (channel.name, channel.name.replace('_','\u2009')))
				await channel.edit(name=channel.name.replace('_','\u2009'))
		return False

	# Handle the addition or removal of reactions
	async def reaction_handler(self,reactionEvent,add=True):
		if not self.membersloaded and self.eventsloaded:
			return
		if reactionEvent.channel_id == CHANNELS['event'] and reactionEvent.message_id in self.eventmap.keys():
			server = self.get_guild(reactionEvent.guild_id)
			channel = self.get_channel(CHANNELS['event'])
			message = await channel.fetch_message(reactionEvent.message_id)
			user = server.get_member(reactionEvent.user_id)
			if user == self.user:
				return
			if add and reactionEvent.emoji.name == EMOJIS['delete'] and await self.is_mod(user):
				await self.del_event("",None,"%s" % self.eventmap.get(message.id))
			else:
				if reactionEvent.user_id in self.memberlist.keys():
					if reactionEvent.emoji.name == EMOJIS['yes'] or reactionEvent.emoji.name == EMOJIS['no']:
						if add:
							await self.add_event_response(reactionEvent.user_id,reactionEvent.message_id,True if reactionEvent.emoji.name == EMOJIS['yes'] else False)
						else:
							await self.remove_event_response(reactionEvent.user_id,reactionEvent.message_id,True if reactionEvent.emoji.name == EMOJIS['yes'] else False)
				elif add:
					if user != self.user:
						await user.send("You are not signed up to raid. Please contact an officer to be added to the raiding list.")

			key = self.eventmap.get(reactionEvent.message_id,False)
			if not key:
				return

			event = self.eventlist.get(key,False)
			if not event:
				return

			for reaction in message.reactions:
				if reaction.emoji == EMOJIS['yes']:
					async for user in reaction.users():
						if user != self.user and user.id not in event['attending']:
							await reaction.remove(user)
				if reaction.emoji == EMOJIS['no']:
					async for user in reaction.users():
						if user != self.user and user.id not in event['declined']:
							await reaction.remove(user)
			await message.add_reaction(EMOJIS['yes'])
			await message.add_reaction(EMOJIS['no'])

	# Add a reaction
	async def on_raw_reaction_add(self,reactionEvent):
		await self.reaction_handler(reactionEvent,True)

	# Remove a reaction
	async def on_raw_reaction_remove(self,reactionEvent):
		await self.reaction_handler(reactionEvent,False)

	# Member leaves server
	async def on_member_remove(self,member):
		if not self.membersloaded and self.eventsloaded:
			return
		if member.id in self.memberlist.keys():
			await self.parse_members(member.guild)

	# Member is updated
	async def on_member_update(self,before,after):
		if not self.membersloaded and self.eventsloaded:
			return
		if len(before.roles) != len(after.roles):
			await self.parse_members(after.guild)

	# Main message handler
	async def on_message(self,message):
		if message.author != self.user:
			if message.channel.id == CHANNELS['event']:
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
						await message.channel.send(msg)

	eventlist = {}
	memberlist = {}
	eventmap = {}

	eventsloaded = False
	membersloaded = False

	commands = {
		'fixevents': {
			'mod' : True,
			'function': fix_events,
			'reply': '',
			'description': '',
			'help' : ''

		},
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
		'getmember': {
			'mod' : True,
			'function': _get_user,
			'reply': '',
			'description': 'Get a member\'s info from the guild list',
			'help' : '%saddmember <Name|@discord>' % TRIGGER

		},
		'setname': {
			'mod' : True,
			'function': set_name,
			'reply': '',
			'description': 'Set a member\'s name. You can get their discord id through discord, or with %sgetmember' % TRIGGER,
			'help' : '%ssetmember <discord_id> <New Name>' % TRIGGER

		},
		'listmembers': {
			'mod' : True,
			'function': list_members,
			'reply': '',
			'description': 'List all of the current raiding members.',
			'help' : '%slistmembers' % TRIGGER

		},
		'parsemembers': {
			'mod' : True,
			'function': parse_members_cmd,
			'reply': '',
			'description': 'Manually trigger a member parse.',
			'help' : '%sparsemembers' % TRIGGER

		},
		'noresponse': {
			'mod' : True,
			'function': noresponse_event,
			'reply': '',
			'description': 'List the people who have not responsed to the specified event.',
			'help' : '%snoresponse <id>' % TRIGGER

		},
		'notify': {
			'mod' : True,
			'function': noresponse_message,
			'reply': '',
			'description': 'Notify anyone who has not responded to the given event via DM with either the default message, or a specified message.',
			'help' : '%snotify <id>\n%snotify <id> [message]' % (TRIGGER,TRIGGER)

		},
		'delevent': {
			'mod' : True,
			'function': del_event,
			'reply': '',
			'description': 'Delete an event',
			'help' : '%sdelevent <id>' % TRIGGER

		},
		'addevent': {
			'mod' : True,
			'function': add_event,
			'reply': '',
			'description': 'Add an event to the event list',
			'help' : '%saddevent "<name>" <date> <description>\n\nEvent name should be in double quotes.\nDate can be a weekday, which it will pick the next of, at the scheduled raid time, or date time in the format of day/month-hour:minute\n\nEx - %saddevent "Molten Core" Sunday We\'re going to clear MC this time\n     %saddevent "BWL" 12/11-18:30 Starting on BWL early at 6:30 this time' % (TRIGGER,TRIGGER,TRIGGER)

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



db = redis.StrictRedis(REDIS['host'])
client = dClient()
client.loop.create_task(client.server_list())
client.run(settings.TOKEN)
db.close()
