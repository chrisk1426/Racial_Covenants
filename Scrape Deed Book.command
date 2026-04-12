#!/bin/bash
# Double-click this file in Finder to run the deed scraper.
# It will open a dialog asking for the book number, then start scraping.

cd "$(dirname "$0")"

# Ask for book number
BOOK=$(osascript -e 'text returned of (display dialog "Enter deed book number to scrape:" default answer "290" with title "Deed Scraper")')
if [ -z "$BOOK" ]; then
    osascript -e 'display alert "Cancelled" message "No book number entered."'
    exit 0
fi

# Ask for last page
END_PAGE=$(osascript -e 'text returned of (display dialog "Enter last page number:" default answer "1000" with title "Deed Scraper")')
if [ -z "$END_PAGE" ]; then
    osascript -e 'display alert "Cancelled" message "No page number entered."'
    exit 0
fi

osascript -e 'display notification "Starting scraper — Chrome will open shortly." with title "Deed Scraper"'

# Run the scraper
python scrape_deeds.py --book "$BOOK" --end-page "$END_PAGE"

# When done, open the web UI
osascript -e 'display notification "Scraping complete! Opening the web UI." with title "Deed Scraper"'
open http://localhost:8000
