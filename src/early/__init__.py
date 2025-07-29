from datetime import datetime, date, timedelta
import os
import re
import requests

class Activity:
    name = ''
    started_at : datetime
    stopped_at : datetime
    jira_key = None
    early_id = ''
    note = {}

    def __init__(self, name, started_at : datetime, stopped_at : datetime, jira_key, early_id : str, note: dict):
        self.name = name
        self.started_at = started_at
        self.stopped_at = stopped_at
        self.jira_key = jira_key
        self.early_id = early_id
        self.note = note

    def __str__(self):
        return f"name='{self.name}', started_at={self.started_at}, stopped_at={self.stopped_at}, jira_key='{self.jira_key}'"

class Early:
    api_url = 'https://api.early.app/api/v4'
    headers = {'Authorization': f'Bearer {os.environ["TOKEN_EARLY"]}'}
    
    tag_failed = ''
    tag_tempo = ''

    def __init__(self):
        tags = self.fetch_tags()
        self.tag_failed = self.get_tag_with_label(tags, 'FAILED')
        self.tag_success = self.get_tag_with_label(tags, 'Tempo')

    def get_activities(self, begin: date, end: date):
        early_entries = self.get_time_entries(begin, end)
        return self.extract_activities(early_entries)

    def get_time_entries(self, begin: date, end: date):
        print(f'Uploading time entries from {begin} to {end}:')
        url = f'{self.api_url}/time-entries/{begin}T00:00:00.000/{end}T23:59:59.999'

        response = requests.get(url, headers=self.headers)
        if response:
            return response.json()
        else:
            response.raise_for_status()
        

    def get_jira_key_from_str(self, str):
        m = re.match(r"^\s*([a-zA-Z]+-\d+)", str)
        if m:
            return m[0]
        else:
            None

    def extract_activities(self, early_entries):
        activities = []
        for early_entry in early_entries["timeEntries"]:
            activities.append(self.extract_activity_from_time_entry(early_entry))
        return activities
    
    def extract_activity_from_time_entry(self, time_entry):
        activity_name = time_entry['activity']['name']
        duration = time_entry['duration']

        return Activity( \
            name = activity_name,
            started_at = datetime.fromisoformat(duration['startedAt']),
            stopped_at = datetime.fromisoformat(duration['stoppedAt']),
            jira_key = self.get_jira_key_from_str(activity_name),
            early_id = time_entry['id'],
            note = time_entry['note']['text']
        )

    def fetch_tags(self):
        url = f'{self.api_url}/tags-and-mentions'

        response = requests.get(url, headers=self.headers)
        data = response.json()
        return data

    def get_tag_with_label(self, tags, label : str):
        for tag in tags['tags']:
            if tag['label'] == label:
                return tag
        return None
        
    def tag_activity(self, activity: Activity, tag, text = ''):
        url = f'{self.api_url}/time-entries/{activity.early_id}'

        response_get = requests.get(url, headers=self.headers)
        data = response_get.json()
        data['note']['text']=f"<{{{{|t|{tag}|}}}}> {text}"

        response = requests.patch(url, headers=self.headers, json = data)
        if not response:
            response.raise_for_status()

    def mark_success(self, activity : Activity):
        self.tag_activity(activity, self.tag_success['id'])

    def mark_fail(self, activity: Activity, error: str):
        self.tag_activity(activity, self.tag_failed['id'], error)

    def contains_tag(self, activity: Activity, tag: dict):
        if activity.note:
            return f"<{{{{|t|{tag['id']}|}}}}>" in activity.note
        else:
            return False

class JIRA:
    api_url = 'https://jira.mvtec.com/rest/api/2'
    headers = {'Authorization': f'Bearer {os.environ["TOKEN_JIRA"]}'}

    def datetime_to_jira_format(self, date_time : datetime) -> str:
        return date_time.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
                    
    def upload_activity(self, activity : Activity):
        url = f'{self.api_url}/issue/{activity.jira_key}/worklog'

        spent_seconds = (activity.stopped_at - activity.started_at).total_seconds()

        response = requests.post(
            url, 
            headers=self.headers, 
            json={
                "started": self.datetime_to_jira_format(activity.started_at),
                "timeSpentSeconds": spent_seconds,
            }
        )

        if response:
            print(f'{activity.jira_key} published: {activity.started_at.day}.{activity.started_at.month}. {spent_seconds}s')
        else:
            try:
                response.raise_for_status()
            except Exception as low_level_exception:
                try: 
                    response_text = response.json()['errorMessages']
                except:
                    response_text = "No response"
                print(f'{activity.jira_key} FAILED   : {activity.started_at.day}.{activity.started_at.month}. {spent_seconds}s')
                raise Exception(f'{response_text}\n{low_level_exception}')

def get_last_week_range_relative_to(relative_date : date):
    weekday = relative_date.weekday() # (Monday=0, Sunday=6)
    start_last_week = relative_date - timedelta(days = weekday + 7) # Last Monday
    end_last_week = start_last_week + timedelta(days=6) # Last Sunday
    return start_last_week, end_last_week

def get_relevant_time_range():
    today = datetime.today().date()
    tomorrow = today + timedelta(days=1)

    if today.month != tomorrow.month: # today is the last day of the month
        end_of_month = today
        start_of_month = today.replace(day=1)
        return start_of_month, end_of_month
    elif today.weekday() < 4 : # if before Friday
        last_week_today = today - timedelta(7)
        return get_last_week_range_relative_to(last_week_today)
    else:
        return get_last_week_range_relative_to(today)


def main():
    early = Early()
    jira = JIRA()

    try:
        begin, end = get_relevant_time_range()
        for activity in early.get_activities(begin, end):
            if activity.jira_key and not early.contains_tag(activity, early.tag_success):
                try:
                    early.mark_success(activity)
                    jira.upload_activity(activity)
                except Exception as e:
                    early.mark_fail(activity, e)
                    print(e)    
    except Exception as e:
        print(e)

