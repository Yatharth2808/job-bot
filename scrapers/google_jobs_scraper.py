from jobspy import scrape_jobs
import pandas as pd
import os

def get_jobs(job_titles, num_results=25):
    all_jobs = []
    
    for job_title in job_titles:
        print(f"Searching for: {job_title}...")
        
        jobs = scrape_jobs(
            site_name=["indeed", "linkedin", "glassdoor", "zip_recruiter"],
            search_term=job_title,
            location="USA",
            results_wanted=num_results,
            hours_old=72,  # jobs posted in last 3 days
            country_indeed='USA'
        )
        
        all_jobs.append(jobs)
        print(f"Found {len(jobs)} jobs for {job_title}")
    
    combined = pd.concat(all_jobs, ignore_index=True)
    return combined

def save_jobs(jobs):
    os.makedirs('data', exist_ok=True)
    jobs.to_csv('data/jobs.csv', index=False)
    print(f"Saved {len(jobs)} total jobs to data/jobs.csv")

if __name__ == "__main__":
    JOB_TITLES = [
        "software engineer",
        "python developer",
        "data analyst",
        "backend engineer",
        "frontend engineer"
    ]
    
    jobs = get_jobs(JOB_TITLES, num_results=25)
    save_jobs(jobs)
    print("Done!")