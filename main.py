from applicator.linkedin_apply import run_apply

JOB_TITLES = [
    "Entry Level Software Developer",
    "Entry Level Data Analyst",
    "Junior Python Developer",
    "Entry Level AI Engineer",
    "Data Science Analyst",
]

if __name__ == "__main__":
    run_apply(JOB_TITLES, max_applications=15)
