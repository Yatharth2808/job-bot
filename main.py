from applicator.linkedin_apply import run_apply

JOB_TITLES = [
    "Entry Level Software Engineer",
    "Entry Level Software Developer",
    "Entry Level Data Analyst",
    "Junior Data Analyst",
    "Entry Level AI Engineer",
    "Entry Level Machine Learning Engineer",
    "Junior Python Developer",
    "Junior Data Scientist",
    "Entry Level Backend Developer",
    "Entry Level Full Stack Developer",
]

if __name__ == "__main__":
    run_apply(JOB_TITLES, max_applications=15)
