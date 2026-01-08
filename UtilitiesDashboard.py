import streamlit as st
import requests
import certifi
import json
from datetime import datetime, timedelta, date
import math
import csv
import io
import urllib3
import sys
# New imports for scraping
from bs4 import BeautifulSoup
import re

# --- 1. PYTHON DATA FETCHING LOGIC ---

# --- Weather Fetching ---
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast?latitude=51.90,52.14&longitude=-8.47,-10.27&current=temperature_2m&daily=time,weathercode,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant&timezone=Europe%2FDublin&forecast_days=3'
ALERTS_CORK_URL = 'https://meteo-api.open-meteo.com/v1/meteoalerts?latitude=51.90&longitude=-8.47&domains=met&forecast_days=3'
ALERTS_KERRY_URL = 'https://meteo-api.open-meteo.com/v1/meteoalerts?latitude=52.14&longitude=-10.27&domains=met&forecast_days=3'

# --- TIDE SCRAPING FUNCTIONS ---

def get_day_suffix(day):
    """Returns the ordinal suffix (st, nd, rd, th) for a given day."""
    if 10 <= day % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return suffix

def scrape_tide_times(location, url, target_days):
    """
    Scrapes tide times for a single location.
    """
    # Set a user-agent to mimic a browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    print(f"--- [DEBUG] Scraping tide times for {location} ---", file=sys.stderr)
    try:
        # Fetch the webpage, disabling SSL verification
        response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status()

        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the specific tide table by its ID
        table = soup.find(id="tide-table")

        if not table:
            print(f"--- [DEBUG] Could not find table with id='tide-table' for {location}. Structure may have changed. ---", file=sys.stderr)
            return None

        # 1. Find Headers (<th>)
        thead = table.find('thead')
        header_row = thead.find('tr') if thead else table.find('tr')
        
        if not header_row:
            print(f"--- [DEBUG] Could not find header row <tr> for {location}. ---", file=sys.stderr)
            return None
        headers = header_row.find_all('th')

        # 2. Find Data Cells (<td>)
        tbody = table.find('tbody')
        data_row = tbody.find('tr') if tbody else None
        
        # If no <tbody>, try to find the *next* <tr> after the header row
        if not data_row and header_row:
            next_row = header_row.find_next_sibling('tr')
            if next_row:
                data_row = next_row
            else:
                # Fallback: find all <tr>s and take the second one
                all_rows = table.find_all('tr')
                if len(all_rows) > 1:
                    data_row = all_rows[1] 
        
        if not data_row:
            print(f"--- [DEBUG] Could not find data row <tr> for {location}. ---", file=sys.stderr)
            return None
            
        data_cells = data_row.find_all('td')

        if not headers or not data_cells or len(headers) != len(data_cells):
            print(f"--- [DEBUG] Table structure mismatch for {location}. Found {len(headers)} headers and {len(data_cells)} cells. ---", file=sys.stderr)
            return None

        # Map days to their tide data
        daily_data = {}
        for i, header_cell in enumerate(headers):
            if i < len(data_cells):
                day_name = " ".join(header_cell.text.split())
                panel_text = data_cells[i].get_text(separator=' ', strip=True)
                tides = re.findall(r"(Low|High) (\d{2}:\d{2}[ap]m) \((\d+\.\d+m)\)", panel_text)
                
                tide_events = []
                for tide in tides:
                    tide_events.append(f"<b>{tide[0]}</b> {tide[1]} ({tide[2]})")
                
                daily_data[day_name] = " | ".join(tide_events)

        # Filter for the target days
        location_tides = {}
        for day in target_days:
            if day in daily_data:
                location_tides[day] = daily_data[day]
            else:
                location_tides[day] = "Data not found"
        
        return location_tides

    except requests.exceptions.RequestException as e:
        print(f"Error fetching page for {location}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An error occurred while processing {location}: {e}", file=sys.stderr)
        
    return None

@st.cache_data(ttl=60) # Cache for 1 minute
def fetch_scraped_tides():
    """Fetches tide data from tidetime.org for Cork and Kerry."""
    locations_to_scrape = {
        "Cork": "https://www.tidetime.org/europe/ireland/cork.htm",
        "Kerry": "https://www.tidetime.org/europe/ireland/fenit.htm" 
    }

    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    next_day = today + timedelta(days=2)

    day_format = lambda dt: f"{dt.strftime('%a')}, {dt.day}{get_day_suffix(dt.day)}"
    target_days_list = [day_format(today), day_format(tomorrow), day_format(next_day)]

    all_scraped_data = {}
    for location, url in locations_to_scrape.items():
        tide_data = scrape_tide_times(location, url, target_days_list)
        if tide_data:
            all_scraped_data[location] = tide_data
        else:
            all_scraped_data[location] = {day: "Data unavailable" for day in target_days_list}

    return all_scraped_data


# --- Modified Weather Fetching Function ---
@st.cache_data(ttl=60) # Cache for 1 minute
def fetch_all_weather():
    """Fetches weather data from Open-Meteo."""
    try:
        with requests.Session() as s:
            # Use verify=False to bypass SSL errors
            forecast_res = s.get(FORECAST_URL, verify=False)
            alerts_cork_res = s.get(ALERTS_CORK_URL, verify=False)
            alerts_kerry_res = s.get(ALERTS_KERRY_URL, verify=False)

            forecast_res.raise_for_status()
            alerts_cork_res.raise_for_status()
            alerts_kerry_res.raise_for_status()

            return {
                "forecasts": forecast_res.json(),
                "alertsCork": alerts_cork_res.json(),
                "alertsKerry": alerts_kerry_res.json(),
            }
    # Catch ALL exceptions to ensure fallback always triggers
    except Exception as e:
        print(f"Error fetching weather data: {e}", file=sys.stderr)
        
        # --- SAFE FALLBACK (No Dummy Data) ---
        return {
            "forecasts": None,
            "alertsCork": {"alerts": []},
            "alertsKerry": {"alerts": []},
        }

# --- Jotform Data Fetching ---
@st.cache_data(ttl=60) # Cache for 1 minute
def fetch_jotform_data():
    """Fetches and processes CSV data from Jotform."""
    url = st.secrets.get("JF") 
    
    if not url:
        st.error("Application Error: Jotform URL is not configured in secrets.")
        return "[]"
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    }
    
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    data_list = []
    
    try:
        response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status()
        
        csv_data = io.StringIO(response.text)
        reader = csv.DictReader(csv_data)
        
        for row in reader:
            priority_val = row.get('Priority')
            if isinstance(priority_val, str):
                priority_num = int(''.join(filter(str.isdigit, priority_val)) or 0)
            elif isinstance(priority_val, (int, float)):
                priority_num = int(priority_val)
            else:
                priority_num = 0

            lat = row.get('Lat')
            lon = row.get('Lon')
            
            processed_row = {
                "Date": row.get('Date', ''),
                "FirstName": row.get('First Name', ''),
                "LastName": row.get('Last Name', ''),
                "Facility": row.get('HSE Facility', ''),
                "Lat": float(lat) if lat else None,
                "Lon": float(lon) if lon else None,
                "Location": row.get('Exact Location of Issue', ''),
                "Utility": row.get('Type of Utility Affected', 'Other'),
                "Description": row.get('Description', ''),
                "Priority": priority_num,
                "Phone": row.get('Phone Number', ''),
                "Email": row.get('Email', ''),
                "Status": row.get('Status', 'Ongoing'),
                "PriorityAfterStatus": row.get('Priority After Status', None)
            }
            data_list.append(processed_row)
        
        return json.dumps(data_list)

    except Exception as e:
        print(f"An error occurred fetching Jotform data: {e}", file=sys.stderr)
    
    return "[]"

# --- 2. ENHANCED HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HSE SouthWest Facilities Dashboard</title>
    <link rel="icon" href="https://www.hse.ie/favicon-32x32.png" type="image/png">
    
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>

    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        :root {
            --hse-teal: #02594C;
            --hse-teal-light: #037362;
            --hse-wine: #8B1538;
            --primary-gradient: linear-gradient(135deg, #02594C 0%, #014D42 100%);
            --glass-bg: rgba(255, 255, 255, 0.85);
            --glass-border: rgba(255, 255, 255, 0.3);
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #f0f4f8 0%, #d9e2ec 100%);
            background-attachment: fixed;
            min-height: 100vh;
            position: relative;
        }
        
        #modalContent {
            /* Ensure modal content is visible when container is visible */
            width: 100%;
            max-width: 42rem;
            display: block; 
        }
        
        .content-wrapper {
            position: relative;
            z-index: 1;
            max-width: 1600px;
            margin: 0 auto;
        }
        
        #map {
            height: 38vh;
            border-radius: 1rem;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.15);
            z-index: 10;
            border: 3px solid rgba(255, 255, 255, 0.5);
            backdrop-filter: blur(10px);
        }
        
        .pro-card {
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }
        
        .pro-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 25px 50px -12px rgba(2, 89, 76, 0.25);
            border-color: rgba(2, 89, 76, 0.3);
        }
        
        .loading-shimmer {
            position: relative;
            overflow: hidden;
        }
        
        .loading-shimmer::after {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            bottom: 0;
            left: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
            animation: shimmer 2s infinite;
        }
        
        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }

        @keyframes ticker {
            0% { transform: translateX(100%); }
            100% { transform: translateX(-100%); }
        }
        
        .ticker-wrap {
            overflow: hidden;
            background: linear-gradient(90deg, rgba(239,68,68,0.15) 0%, rgba(239,68,68,0.05) 50%, rgba(239,68,68,0.15) 100%);
            backdrop-filter: blur(10px);
            border: 2px solid rgba(239, 68, 68, 0.3);
        }
        
        .ticker {
            display: inline-block;
            white-space: nowrap;
            animation: ticker 30s linear infinite;
            padding-right: 100%;
        }
        
        .header-gradient {
            background: var(--primary-gradient);
            box-shadow: 0 10px 40px -10px rgba(2, 89, 76, 0.4);
            border-bottom: 4px solid var(--hse-teal-light);
        }
        
        .priority-badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.75rem;
            letter-spacing: 0.025em;
        }
        
        .chart-bar {
            transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .data-unavailable {
            font-style: italic;
            color: #9ca3af;
        }

        @media (max-width: 768px) {
            #map {
                height: 25vh;
            }
        }
        
        .fade-in {
            animation: fadeIn 0.6s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="content-wrapper">
        <header class="mb-6 px-4 py-4 sm:px-6 sm:py-5 rounded-2xl shadow-2xl flex flex-col sm:flex-row justify-between items-start sm:items-center header-gradient fade-in">
            <div class="flex flex-col items-center sm:flex-row sm:items-center text-center sm:text-left mb-4 sm:mb-0 w-full sm:w-auto">
                <div class="bg-white/15 backdrop-blur-md p-3 rounded-xl sm:mr-4 mb-3 sm:mb-0 shadow-lg">
                    <img src="https://www.hse.ie/image-library/hse-site-logo-2021.svg" alt="HSE Logo" class="h-14">
                </div>
                <div class="w-full sm:w-auto">
                    <h1 class="text-2xl sm:text-3xl font-black text-white tracking-tight">
                        HSE SouthWest Facilities Dashboard
                    </h1>
                    <p class="text-teal-100 text-sm mt-1 font-medium">Real-time Infrastructure Monitoring & Safety Management</p>
                </div>
            </div>
            <div class="flex flex-col items-start w-full sm:w-auto sm:items-end space-y-3">
                <div class="flex flex-col sm:flex-row items-start sm:items-center space-y-3 sm:space-y-0 sm:space-x-3">
                    <span class="text-white font-semibold text-xs uppercase tracking-wider">Map View:</span>
                    <button id="mapToggle" class="px-5 py-2.5 rounded-lg transition-all shadow-lg bg-blue-600 text-white hover:bg-blue-700 text-xs font-bold uppercase tracking-wide">
                        By Utility
                    </button>
                    <span class="text-white font-semibold text-xs uppercase tracking-wider ml-0 sm:ml-3">Filter:</span>
                    <button id="toggleButton" class="px-5 py-2.5 rounded-lg transition-all shadow-lg bg-red-600 text-white hover:bg-red-700 text-xs font-bold uppercase tracking-wide">
                        Ongoing Only
                    </button>
                </div>
                <div id="live-clock" class="text-sm font-semibold text-white text-left sm:text-right w-full mt-2"></div>
            </div>
        </header>

        <div id="safetyAlertsTicker" class="mb-6 rounded-2xl overflow-hidden shadow-xl fade-in"></div>

        <div class="mb-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 fade-in"> 
            <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-slate-500">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">Total Issues</div>
                        <div id="totalCard" class="stat-number text-5xl font-black text-gray-900 mb-1">0</div>
                        <div class="text-xs text-gray-500 font-medium">Ongoing + Completed</div>
                    </div>
                    <div class="bg-slate-100 p-4 rounded-xl">
                        <svg class="w-8 h-8 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
                    </div>
                </div>
            </div>
            <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-red-500">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-xs font-bold text-red-500 uppercase tracking-widest mb-2">Ongoing Issues</div>
                        <div id="ongoingCard" class="stat-number text-5xl font-black text-red-700 mb-1">0</div>
                        <div class="text-xs text-red-500 font-medium">Requires attention</div>
                    </div>
                    <div class="bg-red-100 p-4 rounded-xl">
                        <svg class="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                    </div>
                </div>
            </div>
            <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-green-500">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-xs font-bold text-green-500 uppercase tracking-widest mb-2">Completed</div>
                        <div id="completeCard" class="stat-number text-5xl font-black text-green-700 mb-1">0</div>
                        <div class="text-xs text-green-500 font-medium">Successfully resolved</div>
                    </div>
                    <div class="bg-green-100 p-4 rounded-xl">
                        <svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                    </div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 fade-in">
            <div class="lg:col-span-2">
                <div id="map" class="loading-shimmer"></div>
            </div>

            <div class="lg:col-span-1 space-y-6">
                <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl">
                    <h3 class="text-lg font-bold text-gray-800 mb-5 flex items-center">
                        <div class="w-1.5 h-7 bg-blue-500 mr-3 rounded-full shadow-md"></div>
                        Issues by Utility Type
                    </h3>
                    <div id="utilityChart" class="flex flex-col space-y-2"></div>
                </div>

                <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl">
                    <h3 class="text-lg font-bold text-gray-800 mb-5 flex items-center">
                        <div class="w-1.5 h-7 bg-orange-500 mr-3 rounded-full shadow-md"></div>
                        Issues by Priority Level
                    </h3>
                    <div id="priorityChartContainer" class="relative" style="height: 250px;">
                        <canvas id="priorityChart"></canvas>
                    </div>
                </div>

                <div class="pro-card bg-gradient-to-br from-gray-50 to-gray-100 p-4 sm:p-6 rounded-2xl shadow-xl border border-gray-200">
                    <h3 class="text-lg font-bold text-gray-800 mb-4 flex items-center">
                        <svg class="w-5 h-5 mr-2 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                        Priority Scale Reference
                    </h3>
                    <ul class="space-y-3 text-sm">
                        <li class="flex items-center font-semibold"><span class="priority-badge bg-red-100 text-red-800 mr-3">P5</span>Critical - Immediate Action Required</li>
                        <li class="flex items-center"><span class="priority-badge bg-orange-100 text-orange-800 mr-3">P3-4</span>High - Urgent Review Needed</li>
                        <li class="flex items-center"><span class="priority-badge bg-yellow-100 text-yellow-800 mr-3">P1-2</span>Low - Scheduled Maintenance</li>
                    </ul>
                </div>
            </div>
        </div>

        <div class="mt-8 pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-blue-400 fade-in">
            <h3 class="text-lg font-bold text-gray-800 mb-5 flex items-center">
                <svg class="w-6 h-6 mr-3 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"/></svg>
                Weather, Tide & Safety Status
            </h3>
            <div id="weatherCardContent" class="text-sm text-gray-600">
                <div class="loading-shimmer h-32 bg-gray-100 rounded-lg"></div>
            </div>
        </div>

        <footer class="mt-12 text-center text-gray-500 text-xs font-medium">
            <div class="mb-12 pt-8 border-t border-gray-300">
                <h3 class="text-lg font-bold text-gray-800 mb-6">Quick Links</h3>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-12 max-w-5xl mx-auto">
                    <a href="https://form.jotform.com/250264606365052" target="_blank" rel="noopener noreferrer" class="pro-card p-4 rounded-2xl shadow-lg hover:shadow-xl transition-all group text-center no-underline">
                        <div class="flex flex-col items-center">
                            <div id="qr-jotform" class="p-2 bg-white rounded-lg shadow-md mb-4 group-hover:opacity-80 transition-opacity w-36 h-36"></div>
                            <span class="font-semibold text-gray-700 group-hover:text-[var(--hse-teal)] transition-colors block">Submit an Issue</span>
                            <span class="text-xs text-gray-500 truncate w-full block">form.jotform.com</span>
                        </div>
                    </a>
                    <a href="https://powercheck.esbnetworks.ie/" target="_blank" rel="noopener noreferrer" class="pro-card p-4 rounded-2xl shadow-lg hover:shadow-xl transition-all group text-center no-underline">
                        <div class="flex flex-col items-center">
                            <div id="qr-esb" class="p-2 bg-white rounded-lg shadow-md mb-4 group-hover:opacity-80 transition-opacity w-36 h-36"></div>
                            <span class="font-semibold text-gray-700 group-hover:text-[var(--hse-teal)] transition-colors block">ESB Power Check</span>
                            <span class="text-xs text-gray-500 truncate w-full block">powercheck.esbnetworks.ie</span>
                        </div>
                    </a>
                    <a href="https://what3words.com/swaps.string.bland" target="_blank" rel="noopener noreferrer" class="pro-card p-4 rounded-2xl shadow-lg hover:shadow-xl transition-all group text-center no-underline">
                        <div class="flex flex-col items-center">
                            <div id="qr-what3words" class="p-2 bg-white rounded-lg shadow-md mb-4 group-hover:opacity-80 transition-opacity w-36 h-36"></div>
                            <span class="font-semibold text-gray-700 group-hover:text-[var(--hse-teal)] transition-colors block">///swaps.string.bland</span>
                            <span class="text-xs text-gray-500 truncate w-full block">what3words.com</span>
                        </div>
                    </a>
                </div>
            </div>
            <p>---</p>
            <p>This dashboard was designed and developed by Dave Maher.</p>
            <p>All associated intellectual property is proprietary.</p>
        </footer>
    </div>

    <!-- MODAL (Using Tailwind classes for structure instead of custom CSS ID to fix display bug) -->
    <div id="modal" class="hidden fixed inset-0 w-full h-full bg-black/60 backdrop-blur-md z-[9999] flex justify-center items-start pt-32">
        <div id="modalContent" class="pro-card rounded-2xl shadow-2xl transition-all duration-300">
        </div>
    </div>

    <script>
        Chart.register(ChartDataLabels); 

        const PRELOADED_WEATHER_DATA = %%WEATHER_DATA_PLACEHOLDER%%;
        const PRELOADED_TIDE_DATA = %%TIDE_DATA_PLACEHOLDER%%;
        const RAW_DATA = %%JOTFORM_DATA_PLACEHOLDER%%;
        
        const UTILITY_COLORS = {
            'Electricity': { bg: 'bg-red-500', text: 'text-red-600', hex: '#ef4444' },
            'Mechanical': { bg: 'bg-blue-500', text: 'text-blue-600', hex: '#3b82f6' },
            'Medical Gases': { bg: 'bg-green-500', text: 'text-green-600', hex: '#22c55e' },
            'IT/Communication': { bg: 'bg-yellow-500', text: 'text-yellow-600', hex: '#f59e0b' },
            'Water': { bg: 'bg-indigo-500', text: 'text-indigo-600', hex: '#6366f1' },
            'Gas': { bg: 'bg-purple-500', text: 'text-purple-600', hex: '#a855f7' },
            'Other': { bg: 'bg-gray-500', text: 'text-gray-600', hex: '#6b7280' },
        };

        const PRIORITY_COLORS = {
            5: { hex: '#b91c1c' },
            4: { hex: '#f97316' },
            3: { hex: '#f59e0b' },
            2: { hex: '#eab308' },
            1: { hex: '#facc15' },
            0: { hex: '#6b7280' },
            'Other': { hex: '#6b7280' }
        };

        let showComplete = false;
        let mapColorMode = 'utility';
        let mapInstance = null;
        let markersLayer = null;
        let priorityChartInstance = null;

        // DOM Elements
        let toggleButton, mapToggle, totalCard, ongoingCard, completeCard;
        let utilityChartEl, priorityChartContainer, priorityChartEl;
        let modalEl, modalContentEl, weatherCardContent;

        function animateNumber(element, target) {
            const start = parseInt(element.textContent) || 0;
            const duration = 1000;
            const startTime = performance.now();
            
            function update(currentTime) {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                const current = Math.floor(start + (target - start) * easeOut);
                element.textContent = current;
                if (progress < 1) requestAnimationFrame(update);
            }
            requestAnimationFrame(update);
        }

        function updateDashboard() {
            const filteredData = RAW_DATA.filter(issue => showComplete || issue.Status === 'Ongoing');
            updateScoreCards(); 
            updateCharts(filteredData);
            updateMap(filteredData);
            animateChartBars();
        }

        function updateScoreCards() {
            const ongoing = RAW_DATA.filter(i => i.Status === 'Ongoing').length;
            const totalCompleteCount = RAW_DATA.filter(i => i.Status === 'Complete').length;
            const totalIssues = ongoing + totalCompleteCount;
            animateNumber(totalCard, totalIssues);
            animateNumber(ongoingCard, ongoing);
            animateNumber(completeCard, totalCompleteCount);
        }

        function updateCharts(data) {
            const utilityCounts = data.reduce((acc, issue) => {
                const utility = issue.Utility || 'Other';
                acc[utility] = (acc[utility] || 0) + 1;
                return acc;
            }, {});
            const utilityChartData = Object.entries(utilityCounts)
                .map(([name, value])=> ({ name, value, color: UTILITY_COLORS[name]?.hex || UTILITY_COLORS['Other'].hex }))
                .sort((a, b) => b.value - a.value);
            
            utilityChartEl.innerHTML = generateBarChartHTML(utilityChartData);

            const priorityCounts = data.reduce((acc, issue) => {
                const p = `P${issue.Priority || 0}`;
                acc[p] = (acc[p] || 0) + 1;
                return acc;
            }, {});
            
            const priorityChartData = Object.entries(priorityCounts)
                .map(([name, value]) => ({ 
                    name, value, priority: parseInt(name.slice(1))
                }))
                .sort((a, b) => b.priority - a.priority);

            updatePriorityPieChart(priorityChartData);
        }

        function updatePriorityPieChart(data) {
            if (priorityChartInstance) priorityChartInstance.destroy();
            
            if (data.length === 0) {
                priorityChartContainer.innerHTML = '<p class="text-center text-gray-500 p-4">No priority data to display.</p>';
                return;
            } else {
                if (!priorityChartContainer.querySelector('canvas')) {
                    priorityChartContainer.innerHTML = '<canvas id="priorityChart"></canvas>';
                }
            }

            const ctx = document.getElementById('priorityChart').getContext('2d');
            const chartData = {
                labels: data.map(d => d.name),
                datasets: [{
                    data: data.map(d => d.value),
                    backgroundColor: data.map(d => PRIORITY_COLORS[d.priority] ? PRIORITY_COLORS[d.priority].hex : PRIORITY_COLORS['Other'].hex),
                    borderColor: '#ffffff',
                    borderWidth: 3
                }]
            };

            priorityChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: chartData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {
                        datalabels: {
                            display: true,
                            color: '#ffffff',
                            font: { weight: 'bold', size: 16, family: "'Inter', sans-serif" },
                            formatter: (value) => value,
                            textShadowBlur: 2,
                            textShadowColor: 'rgba(0, 0, 0, 0.5)'
                        },
                        legend: {
                            position: 'right',
                            labels: {
                                font: { family: "'Inter', sans-serif", size: 13, weight: '600' },
                                boxWidth: 14,
                                padding: 18,
                                usePointStyle: true,
                                pointStyle: 'circle'
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { family: "'Inter', sans-serif", size: 14, weight: 'bold' },
                            bodyFont: { family: "'Inter', sans-serif", size: 13 },
                            callbacks: {
                                label: function(context) {
                                    let label = context.label || '';
                                    if (label) label += ': ';
                                    if (context.parsed !== null) label += context.parsed + ' issues';
                                    return label;
                                }
                            }
                        }
                    },
                    animation: { animateRotate: true, animateScale: true, duration: 1000, easing: 'easeInOutQuart' }
                }
            });
        }

        function generateBarChartHTML(data) {
            if (data.length === 0) return '<p class="text-center text-gray-500 p-4">No data to display.</p>';
            const maxValue = Math.max(...data.map(d => d.value));
            return data.map(item => `
                <div class="flex items-center space-x-3 group">
                    <span class="text-sm font-semibold w-36 text-gray-700 truncate transition-colors group-hover:text-gray-900" title="${item.name}">${item.name}</span>
                    <div class="flex-grow bg-gray-100 rounded-full h-5 overflow-hidden shadow-inner">
                        <div class="chart-bar h-full rounded-full flex items-center justify-end pr-3 text-xs font-bold text-white shadow-md"
                             style="width: 0%; background: linear-gradient(90deg, ${item.color}, ${item.color}dd); min-width: 10%;"
                             data-width="${maxValue > 0 ? (item.value / maxValue) * 100 : 0}">
                            ${item.value}
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function animateChartBars() {
            setTimeout(() => {
                document.querySelectorAll('.chart-bar').forEach(bar => {
                    const width = bar.getAttribute('data-width');
                    bar.style.width = width + '%';
                });
            }, 100);
        }

        function getRadiusByPriority(priority) {
            switch (priority) {
                case 5: return 13;
                case 4: return 11;
                case 3: return 9;
                case 2: return 7;
                case 1: return 6;
                default: return 7;
            }
        }

        function updateMap(data) {
            if (!mapInstance || !markersLayer) {
                console.error("Map or markers layer not initialized.");
                return;
            }
            markersLayer.clearLayers();
            if (data.length === 0) return;

            data.forEach(issue => {
                if (issue.Lat != null && issue.Lon != null) {
                    let color;
                    if (mapColorMode === 'utility') {
                        color = UTILITY_COLORS[issue.Utility]?.hex || UTILITY_COLORS['Other'].hex;
                    } else {
                        const p = issue.Priority || 0;
                        color = PRIORITY_COLORS[p] ? PRIORITY_COLORS[p].hex : PRIORITY_COLORS['Other'].hex;
                    }

                    const marker = L.circleMarker([issue.Lat, issue.Lon], {
                        radius: getRadiusByPriority(issue.Priority),
                        color: color,
                        weight: 3,
                        fillColor: color,
                        fillOpacity: 0.7,
                        className: 'marker-pulse'
                    }).addTo(markersLayer);

                    marker.on('click', () => {
                        showModal(issue);
                    });
                }
            });
            
            if (window.innerWidth <= 768) {
                mapInstance.setView([52.1, -9.5], 8);
            } else if (markersLayer.getLayers().length > 0) {
                mapInstance.fitBounds(markersLayer.getBounds().pad(0.1));
            }
        }

        function showModal(issue) {
            const color = UTILITY_COLORS[issue.Utility] || UTILITY_COLORS['Other'];
            const statusColor = issue.Status === 'Ongoing' ? 'text-red-600' : 'text-green-600';
            const p = issue.Priority || 0;
            const priorityBadge = `<span class="priority-badge bg-${p === 5 ? 'red' : p >= 3 ? 'orange' : p >= 1 ? 'yellow' : 'gray'}-100 text-${p === 5 ? 'red' : p >= 3 ? 'orange' : p >= 1 ? 'yellow' : 'gray'}-800">P${p}</span>`;

            modalContentEl.innerHTML = `
                <div class="p-4 sm:p-5 rounded-t-2xl text-white flex justify-between items-center" style="background: linear-gradient(135deg, ${color.hex}, ${color.hex}dd);">
                    <h2 class="text-2xl font-bold truncate pr-4">${issue.Facility}</h2>
                    <button id="closeModalButton" class="text-white hover:bg-white hover:bg-opacity-20 rounded-full p-2 transition">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
                <div class="bg-white p-4 sm:p-7 space-y-5 rounded-b-2xl" style="max-height: 70vh; overflow-y: auto;">
                    <div class="grid grid-cols-2 gap-5">
                        <div class="bg-gray-50 p-4 rounded-xl border border-gray-200">
                            <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Utility Affected</p>
                            <p class="text-lg font-bold ${color.text}">${issue.Utility}</p>
                        </div>
                        <div class="bg-gray-50 p-4 rounded-xl border border-gray-200">
                            <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Status / Priority</p>
                            <p class="text-lg font-bold ${statusColor} flex items-center">${issue.Status} ${priorityBadge}</p>
                        </div>
                    </div>
                    <div class="pt-2">
                        <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Issue Description</p>
                        <div class="bg-gradient-to-br from-gray-50 to-gray-100 p-4 rounded-xl border border-gray-200 max-h-40 overflow-y-auto shadow-inner">
                            <p class="text-gray-800 text-base leading-relaxed">${issue.Description}</p>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-5 border-t-2 border-gray-100 pt-5">
                        <div class="bg-blue-50 p-4 rounded-xl border border-blue-100">
                            <p class="text-xs font-bold text-blue-600 uppercase tracking-wider mb-2">Reported By</p>
                            <p class="text-gray-900 font-semibold">${issue.FirstName} ${issue.LastName}</p>
                            <p class="text-sm text-gray-600 mt-1">${issue.Email}</p>
                        </div>
                        <div class="bg-purple-50 p-4 rounded-xl border border-purple-100">
                            <p class="text-xs font-bold text-purple-600 uppercase tracking-wider mb-2">Time & Location</p>
                            <p class="text-gray-900 font-semibold">${issue.Date}</p>
                            <p class="text-sm text-gray-600 mt-1">${issue.Location || 'N/A'}</p>
                        </div>
                    </div>
                </div>
            `;
            modalEl.classList.remove('hidden');
            document.getElementById('closeModalButton').addEventListener('click', hideModal);
        }

        function hideModal() {
            modalEl.classList.add('hidden');
            modalContentEl.innerHTML = '';
        }

        function degreesToCardinal(deg) {
            if (deg === null || deg === undefined) return '';
            const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
            const val = Math.floor((deg / 22.5) + 0.5);
            return dirs[val % 16] || '';
        }

        function getOrdinal(n) {
            const s = ["th", "st", "nd", "rd"];
            const v = n % 100;
            return n + (s[(v - 20) % 10] || s[v] || s[0]);
        }

        function getWeatherDescription(code) {
            const descriptions = {
                0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
                45: 'Fog', 48: 'Freezing fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Intense drizzle',
                61: 'Slight rain', 63: 'Rain', 65: 'Heavy rain', 80: 'Slight showers', 81: 'Showers',
                82: 'Violent showers', 95: 'Thunderstorm', 96: 'Thunderstorm + hail', 99: 'Thunderstorm + heavy hail'
            };
            return descriptions[code] || 'Weather code ' + code;
        }

        function loadSafetyAlerts() {
            const tickerEl = document.getElementById('safetyAlertsTicker');
            try {
                if (!PRELOADED_WEATHER_DATA || !PRELOADED_WEATHER_DATA.alertsCork || !PRELOADED_WEATHER_DATA.alertsKerry) {
                    tickerEl.style.display = 'none';
                    return;
                }
                const { alertsCork, alertsKerry } = PRELOADED_WEATHER_DATA;
                const allAlerts = [];
                if (alertsCork.alerts) alertsCork.alerts.forEach(a => allAlerts.push({location: 'CORK', headline: a.headline || a.event, severity: a.severity}));
                if (alertsKerry.alerts) alertsKerry.alerts.forEach(a => allAlerts.push({location: 'KERRY', headline: a.headline || a.event, severity: a.severity}));

                if (allAlerts.length === 0) {
                    tickerEl.innerHTML = `
                        <div class="bg-gradient-to-r from-green-50 to-emerald-50 border-2 border-green-300 p-4 flex items-center rounded-2xl shadow-lg">
                            <svg class="w-7 h-7 text-green-600 mr-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            <span class="font-bold text-green-800 text-base">✓ NO ACTIVE WEATHER WARNINGS</span>
                            <span class="ml-4 text-green-600 text-sm">All regions clear - Normal operations</span>
                        </div>`;
                    return;
                }
                const tickerContent = allAlerts.map(alert => `
                    <span class="inline-flex items-center mx-8">
                        <svg class="w-5 h-5 text-red-600 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                        <span class="font-bold text-red-700">${alert.location}:</span>
                        <span class="ml-2 text-gray-800">${alert.headline}</span>
                    </span>`).join('');
                tickerEl.innerHTML = `<div class="ticker-wrap p-4 rounded-2xl shadow-lg"><div class="flex items-center"><span class="bg-red-600 text-white px-4 py-2 rounded-lg font-bold text-sm mr-4 flex-shrink-0 shadow-md">⚠ ALERT</span><div class="ticker font-semibold text-sm">${tickerContent}${tickerContent}</div></div></div>`;
            } catch (error) { tickerEl.style.display = 'none'; }
        }

        function loadWeatherData() {
            try {
                if (!PRELOADED_WEATHER_DATA && !PRELOADED_TIDE_DATA) throw new Error('Data missing');
                const { forecasts, alertsCork, alertsKerry } = PRELOADED_WEATHER_DATA || {};
                const tides = PRELOADED_TIDE_DATA || {};
                let isWeatherAvailable = (forecasts && forecasts.length >= 2 && forecasts[0] && forecasts[1]);
                let cork, kerry;
                if (isWeatherAvailable) { cork = forecasts[0]; kerry = forecasts[1]; }

                let summaryHtml = '<div class="grid grid-cols-1 sm:grid-cols-2 gap-4 flex-grow">';
                if (isWeatherAvailable) {
                    summaryHtml += `
                        <div class="text-center bg-gradient-to-br from-blue-50 to-cyan-50 p-4 rounded-xl border-2 border-blue-200 shadow-md">
                            <strong class="block text-2xl font-bold text-gray-900">Cork</strong> 
                            <span class="block text-2xl font-black text-blue-600 mt-1">${cork.current.temperature_2m}°C</span>
                        </div>
                        <div class="text-center bg-gradient-to-br from-blue-50 to-cyan-50 p-4 rounded-xl border-2 border-blue-200 shadow-md">
                            <strong class="block text-2xl font-bold text-gray-900">Kerry</strong> 
                            <span class="block text-2xl font-black text-blue-600 mt-1">${kerry.current.temperature_2m}°C</span>
                        </div>`;
                } else {
                    summaryHtml += `
                        <div class="text-center bg-gray-50 p-4 rounded-xl border-2 border-gray-200 shadow-sm opacity-70">
                            <strong class="block text-xl font-bold text-gray-700">Cork Weather</strong><span class="block text-lg font-bold text-gray-500 mt-1">N/A</span>
                        </div>
                        <div class="text-center bg-gray-50 p-4 rounded-xl border-2 border-gray-200 shadow-sm opacity-70">
                            <strong class="block text-xl font-bold text-gray-700">Kerry Weather</strong><span class="block text-lg font-bold text-gray-500 mt-1">N/A</span>
                        </div>`;
                }
                summaryHtml += '</div>';

                const today = new Date();
                const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
                const dayAfter = new Date(today); dayAfter.setDate(today.getDate() + 2);
                
                const formatDate = (date, prefix) => {
                    const d = date.toLocaleDateString('en-IE', { weekday: 'long' });
                    const m = date.toLocaleDateString('en-IE', { month: 'long' });
                    return (prefix.toLowerCase() === d.toLowerCase()) ? `${d} ${getOrdinal(date.getDate())} of ${m} ${date.getFullYear()}` : `${prefix} ${d} ${getOrdinal(date.getDate())} of ${m} ${date.getFullYear()}`;
                };
                const dayLabels = [formatDate(today, 'Today'), formatDate(tomorrow, 'Tomorrow'), formatDate(dayAfter, dayAfter.toLocaleDateString('en-IE', { weekday: 'long' }))];

                let detailHtml = '<div class="grid grid-cols-1 md:grid-cols-3 gap-6">';
                
                // Weather Column
                detailHtml += '<div class="space-y-3"><h4 class="text-base font-bold text-gray-800 border-b-2 border-blue-300 pb-2 mb-3 flex items-center">3-Day Weather Forecast</h4>';
                for (let i = 0; i < 3; i++) {
                    if (isWeatherAvailable) {
                        const cw = getWeatherDescription(cork.daily.weathercode[i]);
                        const kw = getWeatherDescription(kerry.daily.weathercode[i]);
                        detailHtml += `
                            <div class="bg-gradient-to-br from-gray-50 to-gray-100 border-2 border-gray-200 p-4 rounded-xl shadow-md transition-shadow hover:shadow-lg">
                                <strong class="text-gray-900 font-bold text-base">${dayLabels[i]}</strong>
                                <div class="text-xs mt-2 space-y-2">
                                    <div class="bg-white p-2 rounded-lg"><div><strong class="text-blue-600">Cork:</strong> ${cork.daily.temperature_2m_min[i]}° / ${cork.daily.temperature_2m_max[i]}°C | ${cw}</div></div>
                                    <div class="bg-white p-2 rounded-lg"><div><strong class="text-blue-600">Kerry:</strong> ${kerry.daily.temperature_2m_min[i]}° / ${kerry.daily.temperature_2m_max[i]}°C | ${kw}</div></div>
                                </div>
                            </div>`;
                    } else {
                        detailHtml += `<div class="bg-gray-50 border-2 border-gray-200 p-4 rounded-xl shadow-sm opacity-60"><strong class="text-gray-500 font-bold text-base">${dayLabels[i]}</strong><div class="text-xs mt-2 text-center py-4 font-semibold text-gray-400">System Unavailable</div></div>`;
                    }
                }
                detailHtml += '</div>';

                // Tides Column
                const cT = tides.Cork || {}; const kT = tides.Kerry || {};
                const cKeys = Object.keys(cT); const kKeys = Object.keys(kT);
                detailHtml += '<div class="space-y-3"><h4 class="text-base font-bold text-gray-800 border-b-2 border-cyan-300 pb-2 mb-3 flex items-center">3-Day High/Low Tides</h4>';
                for (let i = 0; i < 3; i++) {
                    const dk = cKeys[i] || kKeys[i] || "Day " + (i+1);
                    const tsC = cT[dk] || '<span class="data-unavailable">Data unavailable</span>';
                    const tsK = kT[dk] || '<span class="data-unavailable">Data unavailable</span>';
                    
                    detailHtml += `
                        <div class="bg-gradient-to-br from-cyan-50 to-blue-50 border-2 border-cyan-200 p-4 rounded-xl shadow-md transition-shadow hover:shadow-lg">
                            <strong class="text-gray-900 font-bold text-base">${dayLabels[i]}</strong>
                            <div class="text-xs mt-2 space-y-2">
                                <div class="bg-white p-2 rounded-lg" id="cork-tide-${i}"></div>
                                <div class="bg-white p-2 rounded-lg" id="kerry-tide-${i}"></div>
                            </div>
                        </div>`;
                    
                    setTimeout(() => {
                        const elC = document.getElementById(`cork-tide-${i}`);
                        const elK = document.getElementById(`kerry-tide-${i}`);
                        if(elC) elC.innerHTML = `<div><strong class="text-cyan-600">Cork:</strong> ${tsC.replace(/ \| /g, '</div><div class="mt-1">')}</div>`;
                        if(elK) elK.innerHTML = `<div><strong class="text-cyan-600">Kerry:</strong> ${tsK.replace(/ \| /g, '</div><div class="mt-1">')}</div>`;
                    }, 0);
                }
                detailHtml += '</div>';

                // Warnings Column
                detailHtml += '<div class="space-y-3"><h4 class="text-base font-bold text-gray-800 border-b-2 border-red-300 pb-2 mb-3 flex items-center">Active Met Éireann Warnings</h4><div class="bg-gradient-to-br from-red-50 to-orange-50 border-2 border-red-200 p-4 rounded-xl shadow-md">';
                const cW = (alertsCork && alertsCork.alerts) ? alertsCork.alerts.map(a=>`<li><strong class="text-red-700">Cork:</strong> ${a.headline}</li>`).join('') : '';
                const kW = (alertsKerry && alertsKerry.alerts) ? alertsKerry.alerts.map(a=>`<li><strong class="text-red-700">Kerry:</strong> ${a.headline}</li>`).join('') : '';
                if(cW || kW) detailHtml += `<ul class="space-y-2 text-sm text-gray-800">${cW}${kW}</ul>`;
                else detailHtml += '<p class="text-sm text-green-700 font-semibold">No active warnings for Cork or Kerry.</p>';
                detailHtml += '</div></div></div>';

                weatherCardContent.innerHTML = `
                    <div id="weatherClickTarget" class="cursor-pointer group">
                        <div class="flex justify-between items-center">${summaryHtml}<div class="ml-4 flex-shrink-0"><svg id="weatherChevron" class="w-8 h-8 text-gray-400 group-hover:text-blue-600 transition-transform duration-300 rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg></div></div>
                        <div id="weatherDetails" class="mt-6 pt-6 border-t-2 border-gray-200">${detailHtml}</div>
                    </div>`;
                
                document.getElementById('weatherClickTarget').addEventListener('click', () => {
                    document.getElementById('weatherDetails').classList.toggle('hidden');
                    document.getElementById('weatherChevron').classList.toggle('rotate-180');
                });

            } catch (e) { weatherCardContent.innerHTML = `<p class="text-red-600 p-4">Error: ${e.message}</p>`; }
        }

        function initMap() {
            try {
                mapInstance = L.map('map').setView([52.1, -9.5], 8);
                L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { attribution: '© OpenStreetMap contributors' }).addTo(mapInstance);
                markersLayer = L.featureGroup().addTo(mapInstance);
                document.getElementById('map').classList.remove('loading-shimmer');
            } catch (e) { document.getElementById('map').innerHTML = '<p class="text-red-600 p-4">Map Error</p>'; }
        }

        document.addEventListener('DOMContentLoaded', () => {
            toggleButton = document.getElementById('toggleButton');
            mapToggle = document.getElementById('mapToggle');
            totalCard = document.getElementById('totalCard');
            ongoingCard = document.getElementById('ongoingCard');
            completeCard = document.getElementById('completeCard');
            utilityChartEl = document.getElementById('utilityChart');
            priorityChartContainer = document.getElementById('priorityChartContainer');
            priorityChartEl = document.getElementById('priorityChart');
            modalEl = document.getElementById('modal');
            modalContentEl = document.getElementById('modalContent');
            weatherCardContent = document.getElementById('weatherCardContent');

            if(!toggleButton) return;

            initMap();
            loadSafetyAlerts();
            loadWeatherData();
            updateDashboard();

            toggleButton.textContent = showComplete ? 'Ongoing Only' : 'Show All';
            
            toggleButton.addEventListener('click', () => {
                showComplete = !showComplete;
                toggleButton.textContent = showComplete ? 'Ongoing Only' : 'Show All';
                toggleButton.className = showComplete ? "px-5 py-2.5 rounded-lg transition-all shadow-lg bg-gray-600 text-white hover:bg-gray-700 text-xs font-bold uppercase tracking-wide" : "px-5 py-2.5 rounded-lg transition-all shadow-lg bg-red-600 text-white hover:bg-red-700 text-xs font-bold uppercase tracking-wide";
                updateDashboard();
            });

            mapToggle.addEventListener('click', () => {
                mapColorMode = mapColorMode === 'utility' ? 'priority' : 'utility';
                mapToggle.textContent = mapColorMode === 'utility' ? 'By Utility' : 'By Priority';
                mapToggle.className = mapColorMode === 'utility' ? "px-5 py-2.5 rounded-lg transition-all shadow-lg bg-blue-600 text-white hover:bg-blue-700 text-xs font-bold uppercase tracking-wide" : "px-5 py-2.5 rounded-lg transition-all shadow-lg bg-orange-600 text-white hover:bg-orange-700 text-xs font-bold uppercase tracking-wide";
                const filteredData = RAW_DATA.filter(issue => showComplete || issue.Status === 'Ongoing');
                updateMap(filteredData);
            });

            modalEl.addEventListener('click', (e) => { if (e.target === modalEl) hideModal(); });

            function updateLiveClock() {
                const now = new Date();
                const d = now.toLocaleDateString('en-IE', { weekday: 'long' });
                const m = now.toLocaleDateString('en-IE', { month: 'long' });
                const t = now.toLocaleTimeString('en-IE', { hour: '2-digit', minute: '2-digit' });
                const el = document.getElementById('live-clock');
                if(el) el.innerHTML = `${d} ${getOrdinal(now.getDate())} of ${m} ${now.getFullYear()} | ${t}`;
            }
            updateLiveClock(); setInterval(updateLiveClock, 1000);

            try {
                const qrSize = 128; const hseGreen = '#02594C';
                if(document.getElementById('qr-jotform')) new QRCode(document.getElementById("qr-jotform"), { text: "https://form.jotform.com/250264606365052", width: qrSize, height: qrSize, colorDark: hseGreen, colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.H });
                if(document.getElementById('qr-esb')) new QRCode(document.getElementById("qr-esb"), { text: "https://powercheck.esbnetworks.ie/", width: qrSize, height: qrSize, colorDark: hseGreen, colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.H });
                if(document.getElementById('qr-what3words')) new QRCode(document.getElementById("qr-what3words"), { text: "https://what3words.com/swaps.string.bland", width: qrSize, height: qrSize, colorDark: hseGreen, colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.H });
            } catch(e) { console.error("QR Error", e); }
        });
    </script>
</body>
</html>
"""

# --- 3. STREAMLIT APP LOGIC ---

def show_dashboard():
    """Fetches data and displays the full HTML dashboard."""
    weather_data = fetch_all_weather()
    tide_data = fetch_scraped_tides()
    jotform_data_json = fetch_jotform_data()
    
    weather_data_json = json.dumps(weather_data) 
    tide_data_json = json.dumps(tide_data)

    html_content = HTML_TEMPLATE.replace("%%WEATHER_DATA_PLACEHOLDER%%", weather_data_json)
    html_content = html_content.replace("%%TIDE_DATA_PLACEHOLDER%%", tide_data_json)
    html_content = html_content.replace("%%JOTFORM_DATA_PLACEHOLDER%%", jotform_data_json)

    st.components.v1.html(html_content, height=2500, scrolling=False) 

def check_password():
    correct_password = st.secrets.get("APP_PASSWORD")
    if not correct_password:
        st.error("Application Error: Password is not configured.")
        return False

    with st.container():
        st.image("https://www.hse.ie/image-library/hse-site-logo-2021.svg", width=200)
        st.title("Secure Access Portal")
        st.info("Please authenticate to proceed to the operations dashboard.")
        
        password = st.text_input("Password", type="password")
        
        if st.button("Authenticate"):
            if password == correct_password:
                st.session_state["password_correct"] = True
                return True
            else:
                st.error("Access Denied. Please check your credentials.")
                return False
    return False

def main():
    st.set_page_config(layout="wide", page_title="HSE SouthWest Facilities Dashboard", page_icon="https://www.hse.ie/favicon-32x32.png")

    if st.session_state.get("password_correct", False):
        show_dashboard()
    else:
        if check_password():
            st.rerun()

if __name__ == "__main__":
    main()
