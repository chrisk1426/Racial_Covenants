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

# Ask for first page
START_PAGE=$(osascript -e 'text returned of (display dialog "Enter first page number:" default answer "1" with title "Deed Scraper")')
if [ -z "$START_PAGE" ]; then
    osascript -e 'display alert "Cancelled" message "No start page entered."'
    exit 0
fi

# Ask for last page
END_PAGE=$(osascript -e 'text returned of (display dialog "Enter last page number:" default answer "1000" with title "Deed Scraper")')
if [ -z "$END_PAGE" ]; then
    osascript -e 'display alert "Cancelled" message "No end page entered."'
    exit 0
fi

osascript -e 'display notification "Starting scraper — Chrome will open shortly." with title "Deed Scraper"'

# Run the scraper
python scrape_deeds.py --book "$BOOK" --start-page "$START_PAGE" --end-page "$END_PAGE"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    osascript -e 'display notification "Scraping complete! Opening the web UI." with title "Deed Scraper"'
    open http://localhost:8000
else
    echo ""
    echo "Scraper exited with error (code $EXIT_CODE). Check the output above."
fi

echo ""
read -p "Press ENTER to close this window..."
