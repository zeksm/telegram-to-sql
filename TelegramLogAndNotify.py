from pyrogram import Client, Filters, RawUpdateHandler
from pyrogram.api import functions, types
from pyrogram.api.errors import FloodWait
import time
from datetime import datetime
import configparser, pymysql_pool
import sys, traceback
import urllib.request as urlreq
import requests

class TelegramBot():

    def __init__(self):
        
        self.client = Client("Listener")
        
        self.client.add_handler(RawUpdateHandler(self.processUpdate))
        
    def run(self):
    
        self.config = configparser.ConfigParser()
        try:
            self.config.read("config.ini")
        except:
            self.logError("Error while loading the config file, exiting", True)
        
        self.setupDBConnection()
        
        print("\nStarting Telegram API connection\n")
        self.client.start()
        print("API connection started")
        
        self.listening = False
        self.chats = self.getChats()
        self.monitoredChats = self.loadMonitoredChatsTable()
        
        self.menu()
            
        self.client.idle()
        
    def menu(self):
        
        help = '''
- COMMANDS -

all - show a list of joined chats/channels/groups in the account
listening - show a list of joined chats/channels/groups we are listening to for updates
add - add hats/channels/groups to the listening list, pass comma-separated list of usernames or ids
remove - remove chats/channels/groups from the listening list, pass comma-separated list of usernames or ids

start - start listening for updates
'''  
        print(help)
        
        while (True):
        
            userInput = input("\nPlease enter command: ")
            try:
                inputSplit = userInput.split(" ", 1)
                command = inputSplit[0].strip()
                
                if (command == "start"):
                    print("\nStarted listening for updates\n")
                    self.listening = True
                    return
                    
                elif (command == "all"):
                    print("\nTITLE - USERNAME - ID")
                    for chatID in self.chats:
                        chat = self.chats[chatID]
                        print(chat[0] + " - " + chat[1] + " - " + str(chatID))
                        
                elif (command == "listening"):
                    if len(self.monitoredChats) > 0:
                        print("TITLE - USERNAME - ID")
                        for chatID in self.monitoredChats:
                            chat = self.monitoredChats[chatID]
                            print(chat[0] + " - " + chat[1] + " - " + str(chatID))
                    else:
                        print("We're not listening to any chats/channels/groups yet")
                        
                elif (command == "add"):
                    if len(inputSplit) == 1:
                        print("No arguments provided")
                        continue
                    items = inputSplit[1].split(",")
                    items = [i.strip() for i in items if i.strip() != ""]
                    self.addChats(items)
                    
                elif (command == "remove"):
                    if len(inputSplit) == 1:
                        print("No arguments provided")
                        continue
                    items = inputSplit[1].split(",")
                    items = [i.strip() for i in items if i.strip() != ""]
                    self.removeChats(items)
                    
                else:
                    print("Sorry, the command was not recognized")
                    
            except:
                self.logError("Sorry, we've encountered an error")
                continue  
                    
    def setupDBConnection(self):
    
        host = self.config["database"]["host"]
        user = self.config["database"]["user"]
        password = self.config["database"]["password"]
        db = self.config["database"]["db"]
        charset = self.config["database"]["charset"]
        dbsettings = {"host": host, "user": user, "password": password, "db": db, "charset": charset}
        try:
            self.pool = pymysql_pool.ConnectionPool(size=1, name='pool', **dbsettings)
        except:
            self.logError("Error while attempting to connect to database, exiting\n", True)
        print("Database connection established")
        
        self.checkTables()
        
    def checkTables(self):
        
        self.chatTable = self.config["database"]["chat_table"]
        self.messageTable = self.config["database"]["message_table"]
        
        tables = {}
        tables["chat"] = {"name": self.chatTable, "statement": "(ID int unsigned not null, Title varchar(255), Username varchar(255), PRIMARY KEY (ID))"}
        tables["message"] = {"name": self.messageTable, "statement": "(ID int unsigned not null auto_increment, Time datetime, Type varchar(255), Chat int unsigned not null, Sender varchar(255), Message text, PRIMARY KEY(ID), FOREIGN KEY (Chat) REFERENCES " + self.chatTable + "(ID))"}

        connection = self.pool.get_connection()
        c = connection.cursor()
        
        for tableType in tables:
        
            table = tables[tableType]
            
            try:
                c.execute("SHOW TABLES LIKE '" + table["name"] + "'")
                result = c.fetchone()
            except:
                self.logError("Error while looking for " + tableType + " table (" + table["name"] + ") in database\n", True)
                
            if result:
                print("Found " + tableType + " table (" + table["name"] + ")")
            else:
                print("Creating " + tableType + " table (" + table["name"] + ")")
                try:
                    c.execute("CREATE TABLE " + table["name"] + " " + table["statement"])
                    connection.commit()
                except:
                    self.logError("Error while creating " + tableType + " table (" + table["name"] + ")\n", True)
                    
        connection.close()
        
    def loadMonitoredChatsTable(self):
        try:
            connection = self.pool.get_connection()
            c = connection.cursor()
            c.execute("SELECT * FROM " + self.chatTable)
            chats = list(c)
            self.monitoredChats = {chat[0]: [chat[1], chat[2]] for chat in chats}
            connection.close()
        except:
            self.logError("Error while getting list of monitored chats/channels/groups from database")
        
        self.cleanUpMonitored()
        
        return self.monitoredChats
        
    def cleanUpMonitored(self):
        delete = []
        for monitored in self.monitoredChats:
            if monitored not in self.chats:
                delete.append(monitored)
        if len(delete) > 0:
            try:
                connection = self.pool.get_connection()
                c = connection.cursor()
                for id in delete:
                    c.execute("DELETE FROM " + self.chatTable + " WHERE ID=" + str(id))
                    del self.monitoredChats[id]
                connection.commit()
                connection.close()
            except:
                self.logError("Error while clearing a monitored chat we no longer are a member of")
                
        
    def getChats(self):
        chats = self.client.send(functions.messages.GetAllChats([]))
        self.chats = chats.chats
        self.supergroupIDs = [chat.id for chat in self.chats if isinstance(chat, types.Channel) and chat.megagroup == True]
        self.chats = {chat.id: [str(chat.title), ("@" if hasattr(chat, "username") and chat.username else "")+(str(chat.username) if hasattr(chat, "username") else "None")] for chat in self.chats} 
        return self.chats
        
    def addChats(self, items):
        new = []
        for item in items:
            print("Adding to monitored: " + item)
            if (item[0] == "@"):
                item = next((key for key, value in self.chats.items() if value[1] == item), None)
            elif not item.isdigit():
                print("Invalid format for: " + item)
                continue
            item = int(item)
            if not item or not item in self.chats:
                print("You haven't joined this channel yet")
                continue
            if item in self.monitoredChats:
                print("You've already added this to listening list")
                continue
            new.append(item)
        if len(new) > 0:
            self.updateMonitoredChatsList(new, "add")
                    
    def removeChats(self, items):
        removed = []
        for item in items:
            print("Removing from monitored: " + item)
            if (item[0] == "@"):
                item = next((key for key, value in self.chats.items() if value[1] == item), None)
                if not item:
                    print("You haven't even joined this channel , check for typing errors")
                    continue
            elif item.isdigit():
                if not int(item) in self.chats:
                    print("You haven't even joined this channel, check for typing errors")
                    continue
                item = int(item)
            else:
                print("Invalid format for: " + item)
                continue
            if not item in self.monitoredChats:
                    print("Already not monitored")
                    continue
            removed.append(item)
        if len(removed) > 0:
            self.updateMonitoredChatsList(removed, "remove")
            
    def updateMonitoredChatsList(self, modified, action):
        try:
            connection = self.pool.get_connection()
            c = connection.cursor()
            for id in modified:
                chat = self.chats[id]
                if action == "add":
                    c.execute("INSERT INTO " + self.chatTable + "(ID, Title, Username) VALUES (%s, %s, %s)", (id, chat[0], chat[1]))
                elif action == "remove":
                    sql = "DELETE FROM " + self.chatTable + " WHERE ID=" + str(id)
                    c.execute(sql)
            connection.commit()
            connection.close()
            for id in modified:
                if action == "remove":
                    del self.monitoredChats[id]
                elif action == "add":
                     self.monitoredChats[id] = self.chats[id]
        except:
            self.logError("Error while updating monitored list in database")
        
        
    def getAdmins(self):

        self.admins = {}

        for group in self.supergroupIDs:
        
            print("Getting admins for: " + str(group))

            groupAdmins = []
            limit = 200
            offset = 0
            filter = types.ChannelParticipantsAdmins()

            while True:
                try:
                    participants = self.client.send(
                        functions.channels.GetParticipants(
                            channel=self.client.resolve_peer(group),
                            filter=filter,
                            offset=offset,
                            limit=limit,
                            hash=0
                        )
                    )
                except FloodWait as e:
                    time.sleep(e.x)
                    continue
                    
                if isinstance(participants, types.channels.ChannelParticipantsNotModified):
                    print("No admin changes")
                    pass

                if not participants.participants:
                    break

                groupAdmins.extend(participants.participants)
                offset += limit
                
            self.admins[group] = [admin.user_id for admin in groupAdmins]
        
        for group in self.admins:
            print(" - " + str(group) + " - ")
            for admin in self.admins[group]:
                print(admin)
            print()
            
        return self.admins
        
    def updateAdmins(self):
        while True:
            time.sleep(20)
            print("Admin list refresh")
            self.admins = self.getAdmins()
        
    def checkIfAdmin(self, channelID, senderID):
        admins = self.admins[channelID]
        if senderID in admins:
            return True
        else:
            return False
            
    def checkIfChannelAdmin(self, channelID, senderID):
        participant = self.client.send(
                        functions.channels.GetParticipant(
                            channel=self.client.resolve_peer(channelID),
                            user_id=self.client.resolve_peer(senderID)
                        )
                    )
        sender = participant.participant
        if isinstance(sender, types.ChannelParticipantCreator) or isinstance(sender, types.ChannelParticipantAdmin):
            return True
        else:
            return False
            
    def checkIfGroupAdmin(self, groupID, senderID):
        chat = self.client.send(
                functions.messages.GetFullChat(groupID)
                )
        participants = chat.full_chat.participants.participants
        for participant in participants:
            if participant.user_id == senderID:
                if isinstance(participant, types.ChatParticipantCreator) or isinstance(participant, types.ChatParticipantAdmin):
                    return True
                else:
                    return False

    def processUpdate (self, client, update, users, chats):
            
            if self.listening:

                if isinstance(update, types.UpdateNewChannelMessage):
                
                    if isinstance(update.message, types.MessageService):
                        return
                
                    chat = chats[update.message.to_id.channel_id]
                    chatInfo = self.extractChatInfo(chat)
                    if int(chatInfo["id"]) not in self.monitoredChats:
                        return
                    sender = update.message.from_id
                    if sender:
                        sender = users[sender]
                        senderInfo = self.extractSenderInfo(sender)
                    else:
                        senderInfo = None
                    if chat.megagroup == True:
                        if self.checkIfChannelAdmin(chatInfo["id"], senderInfo["id"]):
                            timestamp = update.message.date
                            message = update.message.message
                            print("Supergroup admin message - " + chatInfo["string"] + (" - Sender: " + senderInfo["string"] if sender else "") + ": " + message)
                            self.recordToDatabase(timestamp, "admin", chatInfo, senderInfo, message)
                            self.sendNotification("admin", chatInfo, senderInfo, message)
                        else:
                            print("Supergroup message not from admin - " + chatInfo["string"] + (" - Sender: " + senderInfo["string"] if sender else "") + ": " + update.message.message)
                    else:
                        timestamp = update.message.date
                        message = update.message.message
                        print("Channel message - " + chatInfo["string"] + (" - Sender: " + senderInfo["string"] if sender else "") + ": " + message)
                        self.recordToDatabase(timestamp, "channel", chatInfo, senderInfo, message)
                        self.sendNotification("channel", chatInfo, "", message)
                                
                elif isinstance(update, types.UpdateChannelPinnedMessage):
                        
                    if update.id != 0:
                        chat = chats[update.channel_id]
                        chatInfo = self.extractChatInfo(chat)
                        if int(chatInfo["id"]) not in self.monitoredChats:
                            return
                        messageInfo = client.get_messages(update.channel_id, update.id)
                        sender = messageInfo.from_user
                        if sender:
                            senderInfo = self.extractSenderInfo(sender)
                        else:
                            senderInfo = None
                        timestamp = messageInfo.date
                        message = messageInfo.text
                        print("New pinned message - " + chatInfo["string"] + (" - Sender: " + senderInfo["string"] if sender else "") + ": " + message)
                        self.recordToDatabase(timestamp, "pinned", chatInfo, senderInfo, message)
                        self.sendNotification("pinned", chatInfo, senderInfo if sender else "", message)
                        
                elif isinstance(update, types.UpdateNewMessage):
                    if isinstance(update.message, types.MessageService):
                        return
                    chat = chats[update.message.to_id.chat_id]
                    chatInfo = self.extractChatInfo(chat)
                    if int(chatInfo["id"]) not in self.monitoredChats:
                        return
                    sender = users[update.message.from_id]
                    senderInfo = self.extractSenderInfo(sender)
                    timestamp = update.message.date
                    message = update.message.message
                    if self.checkIfGroupAdmin(chatInfo["id"], senderInfo["id"]):
                        print("Group admin message - " + chatInfo["string"] + (" - Sender: " + senderInfo["string"] if sender else "") + ": " + message)
                        self.recordToDatabase(timestamp, "admin", chatInfo, senderInfo, message)
                        self.sendNotification("admin", chatInfo, senderInfo, message)
                    else:
                        print("Group message not from admin - " + chatInfo["string"] + (" - Sender: " + senderInfo["string"] if sender else "") + ": " + message)
                    
            elif isinstance(update, types.UpdateChannel):
                #print("Channel list changed")
                self.chats = self.getChats()
                self.cleanUpMonitored()
                
    def extractChatInfo(self, chat):
        chatInfo = {}
        chatInfo["title"] = chat.title
        chatInfo["id"] = chat.id
        if hasattr(chat, "username"):
            chatInfo["username"] = ("@" if chat.username else "") + str(chat.username)
        else:
            chatInfo["username"] = "None"
        chatInfo["string"] = chatInfo["title"] + "(" + chatInfo["username"] + ")"
        return chatInfo
    
    def extractSenderInfo(self, sender):
        senderInfo = {}
        senderInfo["id"] = sender.id
        senderInfo["name"] = sender.first_name + (" " + str(sender.last_name) if sender.last_name else "")
        if hasattr(sender, "username"):
            senderInfo["username"] = ("@" if sender.username else "") + str(sender.username)
        else:
            senderInfo["username"] = "None"
        senderInfo["string"] = senderInfo["name"] + "(" + senderInfo["username"] + ")" 
        return senderInfo
            
    def recordToDatabase(self, timestamp, type, chat, sender, message):
        time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        chat = chat["id"]
        if sender:
            sender = sender["string"]
        else:
            sender = ""
        try:
            connection = self.pool.get_connection()
            c = connection.cursor()
            c.execute("INSERT INTO " + self.messageTable + "(Time, Type, Chat, Sender, Message) VALUES (%s, %s, %s, %s, %s)", (time, type, chat, sender, message))
            connection.commit()
            connection.close()
        except:
            self.logError("Error while writing update to the database")
        
    def sendNotification(self, type, chat, sender, message):
        URL = self.config["IFTTT"]["URL"]
        if URL != "":
            text = "New " + type + " message in " + chat["string"] + (" from " + sender["string"] if sender else "") + "\n\n" + message
            #print(text)
            data = {"value1": text}
            try:
                response = requests.post(URL, data=data)
                print(response.text)
            except:
                self.logError("Error while sending notification to phone")
        
    def logError(self, message, fatal=False):
    
        print(message)
        error = str(sys.exc_info()[0]) + "\n\n" + str(sys.exc_info()[1])
        print (error)
        with open("errors.log", 'a') as logfile:
                logfile.write("\n" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " - " + error + "\n\n" + str(traceback.format_exc()) + "\n")
                logfile.write("---------------------------------------------------------------")
        if (fatal):
            #sprint ("\n" + str(traceback.format_exc()))
            raise SystemExit
            
    
if __name__ == "__main__":

    bot = TelegramBot()
    bot.run()