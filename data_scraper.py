from selenium import webdriver
from bs4 import BeautifulSoup
import requests
import time
import random
import pandas as pd
import re
import os
# ==========================================================
# Fase 1 - MATCH EXTRACTION FUNCTION
# ==========================================================
def extract_full_match(url,driver):
    """
    Open a match page on Flashscore and extract the date, teams, score, and the complete statistics table.
    Returns a dictionary with the information. If anything fails, returns a dictionary with None values.
    """
    match_data={
        'date': None,
        'hour' : None,
        'url': url,
        'local_team': None,
        'visiting_team': None,
        'local_goals' : None,
        'visiting_goals' : None,
        'statistics': None
    }
    try:
        print(f"Loading match: {url}")
        driver.get(url) # Opens url with selenium
        # Flashscore uses js, if read too fast, content wont be loaded
        time.sleep(5)       # TO DO: Change to WebDriverWait
        soup=BeautifulSoup(driver.page_source,'html.parser')
        # 1. Date - Check CSS element with " startTime"
        date_element=soup.find('div',class_='duelParticipant__startTime')
        if date_element:
            match_data['date'],match_data['hour']=date_element.text.strip().split()
        # 2. Teams
        local=soup.select_one('.duelParticipant__home a.participant__participantName')
        visiting=soup.select_one('.duelParticipant__away a.participant__participantName')
        if local and visiting:
            match_data['local_team']=local.text.strip()
            match_data['visiting_team']=visiting.text.strip()
        # 3. Score
        score=soup.select_one('.detailScore__wrapper')
        if score:
            local_goals,visiting_goals=score.text.split('-')
            match_data['local_goals'],match_data['visiting_goals']=int(local_goals),int(visiting_goals)
        # 4. Statistics

      


        
    except Exception:
        print(f"Error {Exception} with URL {url}")
    return match_data

    