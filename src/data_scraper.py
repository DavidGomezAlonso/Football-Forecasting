"""
World Cup scraper — extraction of matches, FIFA rankings and market value
================================================================================

What this script does, in three phases:

  1. MATCHES: downloads the match-by-match statistics from Flashscore,
     using the URLs listed in Data/urls.txt. That file includes ALL the
     World Cup matches up to the final — this way, anyone who runs this
     script has the whole competition available to build the model they
     want, not just the specific subset I used in the masterclass.

  2. HISTORICAL FIFA RANKINGS: downloads the FIFA ranking at different
     dates over the last few years, to know the level of each national team
     at the exact moment of each match (not its current level, which would
     be cheating).

  3. MARKET VALUE: downloads the market value of each national team from
     Transfermarkt, as a proxy for the level of the squad.

RUNTIME WARNING: this script takes a LONG time to run. There are dozens of
matches and dozens of historical rankings, each one with a safety pause of
several seconds between request and request (so as not to overload the
servers or trip any anti-bot system). Complete, it can easily take more than
an hour. If you just want to see how it works, first try with a urls.txt
trimmed down to 2-3 matches before launching it in full.

And if what you want is the data, you have it in the Community Course.

PREREQUISITE: this script does NOT open Chrome by itself — it connects to a
Chrome window that YOU already have open manually, with remote debugging
mode enabled (port 9222). This avoids many bot detection problems. To open
Chrome this way, launch it from a terminal with:

    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222

(on Mac/Linux, the same flag on the Chrome binary).
"""

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import requests
import time
import random
import pandas as pd
import re
import os
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
# ==========================================================
# Phase 1 - MATCH EXTRACTION FUNCTION
# ==========================================================

def normalize_strings(text):
    return (text.replace(' ', '_')
                .replace('(', '')
                .replace(')', '')
                .replace('á', 'a')
                .replace('í', 'i')
                .replace('ó', 'o'))
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
        contents=soup.select_one('.statisticsContent').find_all('div',recursive=False)
        for sections in contents:
            subcontents=sections.select_one('.statisticsSection').find_all('div',recursive=False)
            for subsections in subcontents:
                data_lists=subsections.get_text(',',strip=True).split(',')
        
                if len(data_lists)==3:
                    local_value,category,visiting_value=data_lists
            
            
                elif len(data_lists)==5:
                    local_value,category,visiting_value=data_lists[0],data_lists[2],data_lists[4]
                else:
                    continue
                category=normalize_strings(category)  
                match_data[f"{category}_local"]=local_value
                match_data[f"{category}_visiting"]=visiting_value

      


        
    except Exception as e:
        print(f"Error {e} with URL {url}")
    return match_data
# ==========================================================
# Phase 2 - Ranking FIFA
# ==========================================================
def extract_fifa_ranking_with_date(url,driver,date):
    """
    Downloads FIFA ranking for a specified date.
    Returns DataFrame containg country, puntuation and date."""
    print(f"Loading the ranking URL for: {date}")
    driver.get(url)
    time.sleep(4)
    # Data is behind a "Show full Clasification" button
    try:
        button=driver.find_element(By.CSS_SELECTOR,'button[aria-label="Mostrar la Clasificación Mundial completa"]')
        driver.execute_script("arguments[0].click();",button)
    except Exception:
        print("Couldn't press Show full Classification button")
    soup=BeautifulSoup(driver.page_source,'html.parser')

    rows = soup.find_all('tr')
    ranking_data = []

    for row in rows:
        columns = row.find_all('td')
        if len(columns) >= 5:
            # The country name is in the second column, but mixed with
            # other texts (flags, codes) — we keep the last "clean" text of
            # that cell, which is the full name.
            team = None
            team_col_texts = list(columns[1].stripped_strings)
            if team_col_texts:
                team = team_col_texts[-1]

            # The score is not always in the same exact column, so we go
            # through the columns from right to left looking for a text that
            # looks like a FIFA score (3-4 digits + 2 decimals).
            points = None
            for col in reversed(columns):
                txt = col.text.strip().replace(',', '').replace('*', '')
                if re.match(r'^\d{3,4}\.\d{2}$', txt):
                    points = float(txt)
                    break

            if team and points:
                ranking_data.append({
                    'Country': team,
                    'Points': points,
                    'Date': date
                })

    df = pd.DataFrame(ranking_data).drop_duplicates(subset=['Country']).reset_index(drop=True)
    return df


# ==========================================
# PHASE 3 — MARKET VALUE EXTRACTION FUNCTIONS
# ==========================================

def clean_market_value(value_str):
    """
    Transfermarkt expresses the market value as text in European format
    with abbreviations ("450,00 mill.", "1,20 mil mill.", "-"). This
    function normalizes everything to a single float number in millions
    of euros.
    """
    v = value_str.replace('€', '').strip()
    if not v or v == '-':
        return 0.0
    v = v.replace(',', '.')
    try:
        if 'mil mill.' in v:
            return float(v.replace('mil mill.', '').strip()) * 1000
        elif 'mill.' in v:
            return float(v.replace('mill.', '').strip())
        elif 'mil' in v:
            return float(v.replace('mil', '').strip()) / 1000
        else:
            return float(v)
    except Exception:
        # If the format is so odd that it doesn't fit any of the previous
        # cases, we'd rather return 0.0 than crash the whole scraping.
        return 0.0


def extract_transfermarkt(output_path):
    """
    Extracts the market value of all the participating national teams from
    Transfermarkt, going through its result pages one by one until no new
    teams appear anymore.

    Unlike Flashscore and FIFA, Selenium is NOT needed here — the
    Transfermarkt HTML already comes complete in the response (it doesn't
    depend on JavaScript), so 'requests' is enough, much faster and lighter.
    """
    base_url = "https://www.transfermarkt.es/weltmeisterschaft/teilnehmer/pokalwettbewerb/FIWC/saison_id/2025/page/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}

    data = []
    page = 1
    previous_page_teams = []

    print("Starting market value extraction from Transfermarkt...")
    while True:
        url = f"{base_url}{page}"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.content, "html.parser")
        tables = soup.find_all("table", class_="items")
        if not tables:
            break

        current_page_teams = []
        for table in tables:
            rows = table.find("tbody").find_all("tr")
            for row in rows:
                columns = row.find_all("td")
                if len(columns) < 5:
                    continue
                name_cell = row.find("td", class_="hauptlink")
                if not name_cell:
                    continue
                team = name_cell.text.strip()
                raw_value = columns[-1].text.strip()
                current_page_teams.append(team)
                data.append({
                    "Team": team,
                    "Market_Value_Millions_Eur": clean_market_value(raw_value)
                })

        # Stop condition: if this page gives us exactly the same teams as
        # the previous one, it means there are no truly new pages left (some
        # websites repeat the last page when you go past the end).
        if current_page_teams == previous_page_teams:
            break
        previous_page_teams = current_page_teams
        page += 1
        time.sleep(1.5)

    df = pd.DataFrame(data).drop_duplicates(subset=['Team'])
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Transfermarkt finished. {len(df)} teams saved to {output_path}")


# ==========================================
# MAIN EXECUTION BLOCK
# ==========================================

if __name__ == "__main__":

    # --- Input/output paths ---
    # The script assumes it lives inside a subfolder (e.g. "01_Scraping/")
    # and that the "Data" folder is one level above. Adjust this if your
    # folder structure is different.
    root_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    URLS_PATH = os.path.join(root_folder, "Data", "urls.txt")
    MATCHES_CSV_PATH = os.path.join(root_folder, "Data", "matches.csv")
    RANKINGS_CSV_PATH = os.path.join(root_folder, "Data", "fifa_ranking.csv")
    TRANSFER_CSV_PATH = os.path.join(root_folder, "Data", "transfermarkt.csv")

    # --- Connection to the Chrome you already have open ---
    print("Starting data extraction pipeline...")
    print("Connecting to Google Chrome (Port 9222)...")

    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    # Selenium downloads by itself the driver that matches the version of
    # Chrome you have installed.
    service = Service()

    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Connection error: {e}")
        print("Have you opened Chrome in remote debugging mode before running this script? Check the warning at the beginning of the file.")
        exit()

    # ---------------------------------------------------------
    # PHASE 1: MATCH EXTRACTION (Flashscore)
    # ---------------------------------------------------------
    print("\n" + "=" * 45)
    print("PHASE 1: MATCH EXTRACTION")
    print("=" * 45)

    try:
        with open(URLS_PATH, 'r', encoding='utf-8') as f:
            match_urls_list = [line.strip() for line in f if line.strip()]
        print(f"{len(match_urls_list)} match URLs have been loaded.")
    except FileNotFoundError:
        print("ERROR: 'urls.txt' cannot be found in the expected path (Data/urls.txt).")
        match_urls_list = []

    all_matches = []

    for idx, url in enumerate(match_urls_list):
        print(f"\n--- Processing match {idx + 1} of {len(match_urls_list)} ---")
        raw_data = extract_full_match(url, driver)

        if raw_data and raw_data['local_team'] is not None:
            all_matches.append(raw_data)
        else:
            print(f"Extraction failed for the URL: {url}")

        # Random pause between match and match — it's not just courtesy to
        # the server, many websites detect and block perfectly regular
        # request patterns (every X exact seconds) as bot traffic.
        if idx < len(match_urls_list) - 1:
            pause = random.uniform(3, 6)
            print(f"Safety pause of {pause:.2f} seconds...")
            time.sleep(pause)

    if all_matches:
        df_matches = pd.DataFrame(all_matches)
        os.makedirs(os.path.dirname(MATCHES_CSV_PATH), exist_ok=True)
        df_matches.to_csv(MATCHES_CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"\nMatch extraction finished. Data saved to '{MATCHES_CSV_PATH}'")
    elif match_urls_list:
        print("\nNo data could be extracted from any match URL.")

    # ---------------------------------------------------------
    # PHASE 2: RANKING EXTRACTION (FIFA)
    # ---------------------------------------------------------
    print("\n" + "=" * 45)
    print("PHASE 2: HISTORICAL RANKING EXTRACTION")
    print("=" * 45)

    # Each URL corresponds to an official FIFA ranking release on a specific
    # date. We keep them as two parallel lists (URL and date).
    ranking_urls_list = [
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=FRS_Male_Football_20260119",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=FRS_Male_Football_20251219",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=FRS_Male_Football_20251119",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=FRS_Male_Football_20251015",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=FRS_Male_Football_20250910",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14870",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14800",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14702",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14597",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14576",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14541",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14506",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14443",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14415",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14338",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14289",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14233",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14212",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14177",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14142",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14079",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id14058",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13974",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13869",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13792",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13750",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13687",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13603",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13554",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13505",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13197",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id13127",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id12770",
        "https://inside.fifa.com/es/fifa-world-ranking/men?dateId=id12406"
    ]

    ranking_dates_list = [
        "01-04-2026", "19-01-2026", "22-12-2025", "19-11-2025", "17-10-2025",
        "18-09-2025", "10-07-2025", "03-04-2025",
        "19-12-2024", "28-11-2024", "24-10-2024", "19-09-2024", "18-07-2024", "20-06-2024", "04-04-2024", "15-02-2024",
        "21-12-2023", "30-11-2023", "26-10-2023", "21-09-2023", "20-07-2023", "29-06-2023", "06-04-2023",
        "22-12-2022", "06-10-2022", "25-08-2022", "23-06-2022", "31-03-2022", "10-02-2022",
        "23-12-2021", "18-02-2021", "10-12-2020", "19-12-2019", "20-12-2018"
    ]

    ranking_dataframes_list = []

    for idx, (url, date) in enumerate(zip(ranking_urls_list, ranking_dates_list)):
        print(f"\n--- Processing ranking link {idx + 1} of {len(ranking_urls_list)} ---")

        df_temp = extract_fifa_ranking_with_date(url, driver, date)

        if df_temp is not None and not df_temp.empty:
            print(f"  Records added: {len(df_temp)}")
            ranking_dataframes_list.append(df_temp)
        else:
            print(f"  Critical failure or empty table at the URL: {url}")

        if idx < len(ranking_urls_list) - 1:
            pause = random.uniform(3, 5)
            print(f"  Safety pause of {pause:.2f} seconds...")
            time.sleep(pause)

    if ranking_dataframes_list:
        df_final_rankings = pd.concat(ranking_dataframes_list, ignore_index=True)
        os.makedirs(os.path.dirname(RANKINGS_CSV_PATH), exist_ok=True)
        df_final_rankings.to_csv(RANKINGS_CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"\nHistorical ranking extraction finished. Total records: {len(df_final_rankings)}")
        print(f"Consolidated file saved to: '{RANKINGS_CSV_PATH}'")
    else:
        print("\nNo ranking data was extracted.")

    # ---------------------------------------------------------
    # PHASE 3: MARKET VALUE EXTRACTION (Transfermarkt)
    # ---------------------------------------------------------
    print("\n" + "=" * 45)
    print("PHASE 3: MARKET VALUE EXTRACTION")
    print("=" * 45)
    extract_transfermarkt(TRANSFER_CSV_PATH)

    print("\n" + "=" * 45)
    print("FULL PROCESS FINISHED")
    print("=" * 45)