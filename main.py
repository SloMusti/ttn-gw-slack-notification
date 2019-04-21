import os
import time
import re
import yaml
import io
import urllib.request, json 
from slackclient import SlackClient

# load config file, to store info separtely and not commit to git
with open("config.yml", 'r') as ymlfile:
    try:
        cfg = yaml.safe_load(ymlfile)
    except yaml.YAMLError as exc:
            print(exc)

# instantiate Slack client
slack_client = SlackClient(cfg["slack"]["token"])
# starterbot's user ID in Slack: value is assigned after the bot starts up
starterbot_id = None

# constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
EXAMPLE_COMMAND = "do"
MENTION_REGEX = "^<@(|[WU].+?)>(.*)"

#note there may be multiple entries, currently taking the last one through iteration, assuming one entry

gw_list={}

def load_gws():
    # load config file, to store info separtely and not commit to git
    with open("config.yml", 'r') as ymlfile:
        try:
            cfg = yaml.safe_load(ymlfile)
        except yaml.YAMLError as exc:
                print(exc)
    for gw in cfg["gw"]:
        gw_list[gw]={"status":"unknown","rx_count":0,"tx_count":0}

def add_gw(id):
    #read
    with open("config.yml", 'r') as ymlfile:
        cfg = yaml.safe_load(ymlfile)
    
    #modify
    cfg["gw"].append(id)

    # Write YAML file
    with io.open('config.yml', 'w', encoding='utf8') as ymlfile:
        yaml.dump(cfg, ymlfile, default_flow_style=False, allow_unicode=True)

def remove_gw(id):
    #read
    with open("config.yml", 'r') as ymlfile:
        cfg = yaml.safe_load(ymlfile)
    
    #modify
    cfg["gw"].remove(id)

    # Write YAML file
    with io.open('config.yml', 'w', encoding='utf8') as ymlfile:
        yaml.dump(cfg, ymlfile, default_flow_style=False, allow_unicode=True)

def parse_bot_commands(slack_events):
    """
        Parses a list of events coming from the Slack RTM API to find bot commands.
        If a bot command is found, this function returns a tuple of command and channel.
        If its not found, then this function returns None, None.
    """
    for event in slack_events:
        if event["type"] == "message" and not "subtype" in event:
            user_id, message = parse_direct_mention(event["text"])
            if user_id == starterbot_id:
                return message, event["channel"]
    return None, None

def parse_direct_mention(message_text):
    """
        Finds a direct mention (a mention that is at the beginning) in message text
        and returns the user ID which was mentioned. If there is no direct mention, returns None
    """
    matches = re.search(MENTION_REGEX, message_text)
    # the first group contains the username, the second group contains the remaining message
    return (matches.group(1), matches.group(2).strip()) if matches else (None, None)

def handle_command(command, channel):
    """
        Executes bot command if the command is known
    """
    # Default response is help text for the user
    default_response = "Not sure what you mean. Try *{}*.".format(EXAMPLE_COMMAND)

    # Finds and executes the given command, filling in response
    response = None
    # This is where you start to implement more commands!
    if command.startswith("status"):
        response = status_gateways()

    elif command.startswith("add"):
        id=command.split()[1]

        if id in cfg["gw"]:
            response = "Gateway exists already"
        else:
            response = "Adding gw to the config: " + id
            add_gw(id)
            load_gws()
            check_gateways(gw_list)
        print(gw_list)

    elif command.startswith("remove"):
        id=command.split()[1]

        if id not in cfg["gw"]:
            response = "Gateway does not exist: " + id
        else:
            response = "Removing gw from the config: " + id
            remove_gw(id)
            load_gws()
            check_gateways(gw_list)
        print(gw_list)

    elif command.startswith(EXAMPLE_COMMAND):
        response = "Sure...write some more code then I can do that!"

    # Sends the response back to the channel
    slack_client.api_call(
        "chat.postMessage",
        channel=channel,
        text=response or default_response
    )

def check_gateways(gw_list):
    message = ""
    for gw_id, gw_status in gw_list.items():
        try:
            if gw_list[gw_id]["status"] is "disabled":
                continue
            with urllib.request.urlopen("http://noc.thethingsnetwork.org:8085/api/v2/gateways/"+gw_id) as url:
                data = json.loads(url.read().decode())
                seconds = time.time()-int(data["time"])/1000000000
                #detect gw going offline
                if gw_status["status"] is "online" and seconds > 35:
                    gw_list[gw_id]["status"] = "offline"
                    message += "{0:30s} went offline = {1:.2f}\r\n".format(gw_id,seconds)

                #detect gw going online
                elif gw_status["status"] is "offline" and seconds <= 35:
                    gw_list[gw_id]["status"] = "online"
                    message += "{0:30s} came online = {1:.2f}\r\n".format(gw_id,seconds)

                #proces gateways of unknown staus, do not generate messages in that case
                elif gw_status["status"] is "unknown":
                    if seconds < 35:
                        gw_list[gw_id]["status"] = "online"
                    else:
                        gw_list[gw_id]["status"] = "offline"
                        gw_list[gw_id]["rx_count"]=int(data["uplink"])
                        gw_list[gw_id]["tx_count"]=int(data["downlink"])
        except urllib.error.HTTPError:
            print("removing from list, gateway not found:" + gw_id)
            gw_list[gw_id]["status"] = "disabled"
        
    if message is not "":
        print(message)
        slack_client.api_call(
            "chat.postMessage",
            mrkdwn="false",
            channel=cfg["slack"]["channel"],
            text=message
        )

def status_gateways():
    #generate status message
    message = ""
    for gw_id, gw_status in gw_list.items():
        with urllib.request.urlopen("http://noc.thethingsnetwork.org:8085/api/v2/gateways/"+gw_id) as url:
            data = json.loads(url.read().decode())
            rx=int(data["uplink"])-gw_status["rx_count"]
            gw_list[gw_id]["rx_count"]=int(data["uplink"])
            tx=int(data["downlink"])-gw_status["tx_count"]
            gw_list[gw_id]["tx_count"]=int(data["downlink"])

            message += "{0:30s} {1:7s} - packets - {2:d}/{3:d}\r\n".format(gw_id,gw_status["status"],rx,tx)
    return "```" + message + "```"

#if __name__ == "__main__":
if slack_client.rtm_connect(with_team_state=False):
    print("Starter Bot connected and running!")
    # Read bot's user ID by calling Web API method `auth.test`
    starterbot_id = slack_client.api_call("auth.test")["user_id"]
    load_gws()
    check_gateways(gw_list)
    while True:
        command, channel = parse_bot_commands(slack_client.rtm_read())
        if command:
            handle_command(command, channel)
        check_gateways(gw_list)
        time.sleep(RTM_READ_DELAY)
else:
    print("Connection failed. Exception traceback printed above.")
