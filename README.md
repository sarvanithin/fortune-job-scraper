# Fortune Job Scraper

Automated job scraper that extracts data/ML/analyst positions from Fortune company career pages and stores them in Google Sheets.

## Features

- 🔄 **Automated Scheduling**: Runs every 6 hours via GitHub Actions
- 🎯 **Smart Filtering**: Filters jobs by keywords (data, ML, analyst, etc.)
- 📊 **Google Sheets Integration**: Reads company URLs and writes job listings
- 🔍 **Deduplication**: Prevents duplicate job entries
- 📑 **Pagination Handling**: Extracts all jobs across multiple pages
- 🌐 **Multi-Platform Support**: Works with Workday, Eightfold, and custom career sites

## Setup

See [SETUP.md](SETUP.md) for detailed setup instructions.

### Quick Start

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Install Playwright browsers: `playwright install chromium`
4. Set up Google Sheets API (see SETUP.md)
5. Configure your Google Sheet ID in `.env`
6. Run: `python src/main.py`

## Configuration

Edit `src/config.py` to customize:
- Keywords to filter jobs
- Scraping delays
- Batch sizes

## Project Structure

```
├── .github/workflows/    # GitHub Actions workflow
├── src/
│   ├── main.py           # Entry point
│   ├── config.py         # Configuration
│   ├── sheets_client.py  # Google Sheets API
│   ├── scraper/          # Scraping engines
│   └── utils/            # Utilities
├── tests/                # Test files
└── requirements.txt      # Dependencies
```

## License

MIT
