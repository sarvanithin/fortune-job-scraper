#!/usr/bin/env python3
"""
Verify which company career URLs are working.
Outputs a CSV with verified URLs.
"""
import asyncio
import csv
import sys
from typing import List, Tuple
from playwright.async_api import async_playwright


async def verify_url(url: str, timeout: int = 15000) -> Tuple[str, bool, str]:
    """
    Verify if a URL is accessible.
    
    Returns:
        Tuple of (url, is_working, status_message)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            
            if response and response.ok:
                # Check if page has job-related content
                content = await page.content()
                content_lower = content.lower()
                
                # Look for job-related keywords
                job_indicators = ['job', 'career', 'position', 'apply', 'opening', 'role', 'work with us']
                has_jobs = any(indicator in content_lower for indicator in job_indicators)
                
                if has_jobs:
                    return (url, True, "OK - Job content found")
                else:
                    return (url, False, "Warning - No job content detected")
            else:
                status = response.status if response else "No response"
                return (url, False, f"Error - HTTP {status}")
                
        except Exception as e:
            error_msg = str(e)[:100]
            return (url, False, f"Error - {error_msg}")
        finally:
            await browser.close()


async def verify_companies_csv(input_csv: str, output_csv: str):
    """Verify all URLs in a companies CSV and output results."""
    
    # Read input CSV
    companies = []
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            companies.append(row)
    
    print(f"Verifying {len(companies)} URLs...")
    
    results = []
    working_count = 0
    
    for i, company in enumerate(companies):
        name = company.get('Company Name', '')
        url = company.get('Career Search URL', '')
        platform = company.get('Platform Type', '')
        
        if not url:
            continue
        
        print(f"  [{i+1}/{len(companies)}] {name}...", end=' ', flush=True)
        
        _, is_working, status = await verify_url(url)
        
        if is_working:
            working_count += 1
            print("✓")
        else:
            print(f"✗ ({status})")
        
        results.append({
            'Company Name': name,
            'Career Search URL': url,
            'Platform Type': platform,
            'Status': 'Working' if is_working else 'Not Working',
            'Details': status,
        })
    
    # Write output CSV
    with open(output_csv, 'w', newline='') as f:
        fieldnames = ['Company Name', 'Career Search URL', 'Platform Type', 'Status', 'Details']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\n=== Summary ===")
    print(f"Total: {len(results)}")
    print(f"Working: {working_count}")
    print(f"Not Working: {len(results) - working_count}")
    print(f"\nResults saved to: {output_csv}")
    
    # Also output a verified-only CSV
    verified_csv = output_csv.replace('.csv', '_verified.csv')
    with open(verified_csv, 'w', newline='') as f:
        fieldnames = ['Company Name', 'Career Search URL', 'Platform Type']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            if r['Status'] == 'Working':
                writer.writerow({
                    'Company Name': r['Company Name'],
                    'Career Search URL': r['Career Search URL'],
                    'Platform Type': r['Platform Type'],
                })
    
    print(f"Verified URLs saved to: {verified_csv}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python verify_urls.py <input.csv> [output.csv]")
        print("Example: python verify_urls.py companies_h1b_250.csv companies_verified.csv")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else 'companies_verification_results.csv'
    
    asyncio.run(verify_companies_csv(input_csv, output_csv))
