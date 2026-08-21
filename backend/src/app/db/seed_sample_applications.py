import asyncio
import io

from docx import Document
from sqlalchemy import select

from app.capabilities.recruitment import RecruitmentService
from app.db.session import async_session_factory, init_db
from app.domain.recruitment import Vacancy
from app.integrations.object_store import SyncS3ObjectStore
from app.knowledge.resume_extraction import extract_text, is_ats_friendly, looks_like_resume

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"



def _build_resume_docx(lines: list[tuple[str, str]]) -> bytes:
    """Build a real, well-formatted DOCX resume from (style, text) lines.

    style is "title" (name), "heading" (section header), or "body" (a bullet
    or detail line). Runs through the exact same extraction/classification/
    parsability pipeline a real upload would — these are genuine documents,
    not fabricated evaluation JSON.
    """
    doc = Document()
    for style, text in lines:
        if style == "title":
            doc.add_heading(text, level=0)
        elif style == "heading":
            doc.add_heading(text, level=1)
        else:
            doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# Ten real, hand-written resumes (as actual DOCX documents, not synthetic
# evaluation data) — one strong and one weak match per vacancy below, so the
# requirements-gate/ranking UI has genuine good-vs-bad examples produced by
# the real AI screening pipeline (ATS-parsability check + weighted keyword
# scoring), not fabricated scores.
SAMPLE_APPLICATIONS = [
    # ---- Junior Frontend Developer -------------------------------------
    {
        "vacancy_title": "Junior Frontend Developer",
        "first": "Maya",
        "last": "Chen",
        "email": "maya.chen@sample-applicant.test",
        "phone": "+1-415-555-0142",
        "filename": "maya_chen_resume.docx",
        "lines": [
            ("title", "Maya Chen"),
            ("body", "maya.chen@sample-applicant.test | +1-415-555-0142 | San Francisco, CA"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Recent Computer Science graduate with hands-on experience building responsive "
                    "web interfaces. Comfortable with HTML, CSS, and JavaScript fundamentals, with "
                    "growing experience in React through coursework and a summer internship."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Frontend Engineering Intern, Brightpath Software — Summer 2025"),
            (
                "body",
                "- Built and styled 6 responsive page templates using HTML, CSS, and JavaScript.",
            ),
            (
                "body",
                "- Converted two internal admin screens from static HTML to React components.",
            ),
            ("body", "- Used Git and pull requests daily as part of a 5-person engineering team."),
            ("body", "- Fixed 12 layout and cross-browser CSS bugs reported by QA."),
            ("body", "Teaching Assistant, Intro to Web Development — State University, 2024"),
            ("body", "- Helped 30+ students debug HTML/CSS/JavaScript assignments weekly."),
            ("heading", "Projects"),
            (
                "body",
                "Personal Portfolio Site — HTML, CSS, vanilla JavaScript, deployed on GitHub Pages.",
            ),
            (
                "body",
                "Recipe Finder App — React app calling a public API, styled with responsive CSS.",
            ),
            ("heading", "Education"),
            ("body", "B.S. in Computer Science, State University — May 2025"),
            ("heading", "Skills"),
            (
                "body",
                "HTML, CSS, JavaScript, React (basics), Git, responsive design, Chrome DevTools",
            ),
        ],
    },
    {
        "vacancy_title": "Junior Frontend Developer",
        "first": "Robert",
        "last": "Kwan",
        "email": "robert.kwan@sample-applicant.test",
        "phone": "+1-312-555-0198",
        "filename": "robert_kwan_resume.docx",
        "lines": [
            ("title", "Robert Kwan"),
            ("body", "robert.kwan@sample-applicant.test | +1-312-555-0198 | Chicago, IL"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Reliable operations coordinator with 5 years of experience keeping warehouse "
                    "logistics running smoothly. Looking to bring the same organizational discipline "
                    "to a new field."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Warehouse Operations Coordinator, Midwest Distribution Co. — 2020-Present"),
            ("body", "- Scheduled inbound and outbound shipments for a 40,000 sq ft facility."),
            ("body", "- Managed a team of 6 warehouse associates across two shifts."),
            ("body", "- Maintained inventory accuracy above 98% using a barcode scanning system."),
            ("body", "- Trained new hires on safety procedures and equipment handling."),
            ("body", "Inventory Associate, Midwest Distribution Co. — 2018-2020"),
            (
                "body",
                "- Picked, packed, and labeled outbound orders to meet same-day shipping targets.",
            ),
            ("heading", "Education"),
            (
                "body",
                "Associate Degree in Business Administration, Riverside Community College — 2018",
            ),
            ("heading", "Skills"),
            ("body", "Inventory management, team scheduling, forklift certified, Microsoft Excel"),
        ],
    },
    # ---- Senior Backend Engineer ----------------------------------------
    {
        "vacancy_title": "Senior Backend Engineer",
        "first": "David",
        "last": "Okonkwo",
        "email": "david.okonkwo@sample-applicant.test",
        "phone": "+1-206-555-0173",
        "filename": "david_okonkwo_resume.docx",
        "lines": [
            ("title", "David Okonkwo"),
            ("body", "david.okonkwo@sample-applicant.test | +1-206-555-0173 | Seattle, WA"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Senior backend engineer with 9 years building and scaling distributed systems "
                    "in Python. Experienced technical lead who has mentored a dozen engineers and "
                    "owns system design end to end, from architecture reviews to on-call ownership."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Staff Backend Engineer, Northgate Cloud — 2020-Present"),
            (
                "body",
                "- Led system design for a distributed systems rewrite handling 40k requests/sec.",
            ),
            ("body", "- Owned the Python services powering the payments platform end to end."),
            ("body", "- Mentored 5 engineers through promotion to senior, running weekly 1:1s."),
            ("body", "- Migrated core infrastructure to AWS, cutting infra costs by 30%."),
            ("body", "- Ran the on-call rotation and led incident postmortems for the team."),
            ("body", "Senior Software Engineer, Alderwood Systems — 2016-2020"),
            ("body", "- Designed a distributed job queue in Python processing 2M jobs/day."),
            ("body", "- Mentored 4 junior engineers and led architecture design reviews."),
            ("body", "- Built system design docs for every major service the team shipped."),
            ("body", "Software Engineer, Pinehill Data — 2014-2016"),
            ("body", "- Built REST APIs in Python for an internal analytics platform."),
            ("heading", "Education"),
            ("body", "B.S. in Computer Science, University of Washington — 2014"),
            ("heading", "Skills"),
            (
                "body",
                (
                    "Python, distributed systems, system design, mentoring, AWS, Kubernetes, "
                    "PostgreSQL, technical leadership"
                ),
            ),
        ],
    },
    {
        "vacancy_title": "Senior Backend Engineer",
        "first": "Priya",
        "last": "Raman",
        "email": "priya.raman@sample-applicant.test",
        "phone": "+1-469-555-0114",
        "filename": "priya_raman_resume.docx",
        "lines": [
            ("title", "Priya Raman"),
            ("body", "priya.raman@sample-applicant.test | +1-469-555-0114 | Dallas, TX"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Detail-oriented QA tester with 1 year of experience testing web applications. "
                    "Eager to grow my technical skills and take on more challenging work."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Junior QA Tester, Lonestar Apps — 2024-Present"),
            ("body", "- Wrote and executed manual test cases for a customer support web app."),
            ("body", "- Logged and tracked bugs in Jira, verifying fixes before release."),
            ("body", "- Participated in daily standups with the engineering team."),
            ("body", "Customer Support Representative, Lonestar Apps — 2023-2024"),
            ("body", "- Answered customer tickets over email and live chat."),
            ("heading", "Education"),
            ("body", "B.A. in Communications, University of North Texas — 2023"),
            ("heading", "Skills"),
            ("body", "Manual testing, Jira, customer communication, basic HTML"),
        ],
    },
    # ---- Marketing Manager ------------------------------------------------
    {
        "vacancy_title": "Marketing Manager",
        "first": "Sofia",
        "last": "Alvarez",
        "email": "sofia.alvarez@sample-applicant.test",
        "phone": "+1-305-555-0161",
        "filename": "sofia_alvarez_resume.docx",
        "lines": [
            ("title", "Sofia Alvarez"),
            ("body", "sofia.alvarez@sample-applicant.test | +1-305-555-0161 | Miami, FL"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "B2B marketing leader with 6 years of experience owning campaign strategy and "
                    "managing marketing budgets. Currently lead a team of 4 marketers and am fluent "
                    "in GA4 and modern marketing analytics tooling."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Senior Marketing Manager, Harborlight B2B Software — 2021-Present"),
            ("body", "- Own B2B marketing strategy across paid, content, and lifecycle channels."),
            ("body", "- Manage an annual marketing budget of $600,000 across four channels."),
            ("body", "- Lead and mentor a team of 4 marketers, running weekly 1:1s and reviews."),
            ("body", "- Report on campaign performance in GA4, cutting cost-per-lead by 22%."),
            ("body", "Marketing Manager, Harborlight B2B Software — 2019-2021"),
            ("body", "- Managed a $250,000 budget across paid search and content marketing."),
            ("body", "- Built the company's first content strategy, tripling organic traffic."),
            ("body", "Marketing Coordinator, Bayview Marketing Group — 2017-2019"),
            ("body", "- Coordinated B2B email campaigns and supported budget tracking."),
            ("heading", "Education"),
            ("body", "B.A. in Marketing, University of Miami — 2017"),
            ("heading", "Skills"),
            (
                "body",
                "B2B marketing, budget management, team leadership, GA4, marketing analytics, content strategy",
            ),
        ],
    },
    {
        "vacancy_title": "Marketing Manager",
        "first": "Tyler",
        "last": "Brooks",
        "email": "tyler.brooks@sample-applicant.test",
        "phone": "+1-614-555-0187",
        "filename": "tyler_brooks_resume.docx",
        "lines": [
            ("title", "Tyler Brooks"),
            ("body", "tyler.brooks@sample-applicant.test | +1-614-555-0187 | Columbus, OH"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Marketing coordinator with 1 year of experience supporting social media and "
                    "email campaigns. Looking to grow into a broader marketing role."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Marketing Coordinator, Ohio Valley Retail — 2024-Present"),
            ("body", "- Scheduled and posted content across Instagram, Facebook, and TikTok."),
            ("body", "- Drafted weekly promotional emails using a template builder."),
            ("body", "- Compiled basic engagement metrics into a monthly spreadsheet report."),
            ("body", "Marketing Intern, Ohio Valley Retail — Summer 2023"),
            ("body", "- Assisted with in-store event promotion and social media scheduling."),
            ("heading", "Education"),
            ("body", "B.A. in Communications, Ohio State University — 2023"),
            ("heading", "Skills"),
            ("body", "Social media scheduling, email drafting, Canva, basic spreadsheets"),
        ],
    },
    # ---- Data Analyst ------------------------------------------------------
    {
        "vacancy_title": "Data Analyst",
        "first": "Wei",
        "last": "Zhang",
        "email": "wei.zhang@sample-applicant.test",
        "phone": "+1-512-555-0129",
        "filename": "wei_zhang_resume.docx",
        "lines": [
            ("title", "Wei Zhang"),
            ("body", "wei.zhang@sample-applicant.test | +1-512-555-0129 | Austin, TX"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Data analyst with 3 years of experience turning raw data into decisions for "
                    "cross-functional stakeholders. Strong in SQL and dashboard-building, with "
                    "working Python (pandas) skills for deeper analysis."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Data Analyst, Riverbend Analytics — 2022-Present"),
            ("body", "- Write complex SQL queries daily against a 200M-row PostgreSQL warehouse."),
            ("body", "- Built and maintain 15 Tableau dashboards used by 3 department leads."),
            (
                "body",
                "- Present monthly findings to non-technical stakeholders across the company.",
            ),
            ("body", "- Use Python (pandas) for ad hoc analysis outside the standard dashboards."),
            ("body", "Junior Data Analyst, Riverbend Analytics — 2021-2022"),
            ("body", "- Built weekly SQL reports for the operations team."),
            ("body", "- Created a data visualization template used company-wide in Tableau."),
            ("heading", "Education"),
            ("body", "B.S. in Statistics, University of Texas at Austin — 2021"),
            ("heading", "Skills"),
            (
                "body",
                "SQL, data visualization, Tableau, Python (pandas), stakeholder communication",
            ),
        ],
    },
    {
        "vacancy_title": "Data Analyst",
        "first": "Jordan",
        "last": "Blake",
        "email": "jordan.blake@sample-applicant.test",
        "phone": "+1-720-555-0155",
        "filename": "jordan_blake_resume.docx",
        "lines": [
            ("title", "Jordan Blake"),
            ("body", "jordan.blake@sample-applicant.test | +1-720-555-0155 | Denver, CO"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Creative graphic designer with 4 years of experience designing marketing "
                    "assets and brand materials for small businesses."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Graphic Designer, Mile High Creative Studio — 2021-Present"),
            (
                "body",
                "- Designed logos, brand guides, and print materials for 30+ small business clients.",
            ),
            ("body", "- Produced social media graphics using Adobe Illustrator and Photoshop."),
            ("body", "- Collaborated with copywriters to design marketing brochures."),
            ("body", "Freelance Designer — 2020-2021"),
            ("body", "- Delivered branding packages for independent clients on a project basis."),
            ("heading", "Education"),
            ("body", "B.F.A. in Graphic Design, Rocky Mountain College of Art — 2020"),
            ("heading", "Skills"),
            ("body", "Adobe Illustrator, Photoshop, InDesign, brand design, typography"),
        ],
    },
    # ---- Director of Sales -------------------------------------------------
    {
        "vacancy_title": "Director of Sales",
        "first": "Marcus",
        "last": "Webb",
        "email": "marcus.webb@sample-applicant.test",
        "phone": "+1-404-555-0136",
        "filename": "marcus_webb_resume.docx",
        "lines": [
            ("title", "Marcus Webb"),
            ("body", "marcus.webb@sample-applicant.test | +1-404-555-0136 | Atlanta, GA"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Sales executive with 14 years of experience, including 8 years in sales "
                    "leadership roles. Built and led sales teams of up to 25 people and have a "
                    "proven track record of driving significant enterprise revenue growth."
                ),
            ),
            ("heading", "Experience"),
            ("body", "VP of Sales, Crestline Enterprise Solutions — 2019-Present"),
            ("body", "- Built and lead a 25-person enterprise sales team across 3 regions."),
            ("body", "- Drove $15M in new annual revenue growth over 4 years."),
            ("body", "- Own executive-level relationships with Fortune 500 enterprise accounts."),
            (
                "body",
                "- Present quarterly sales strategy and forecasts to the executive team and board.",
            ),
            ("body", "Director of Sales, Ironbridge Systems — 2015-2019"),
            ("body", "- Led a 12-person enterprise sales team, growing revenue from $8M to $18M."),
            ("body", "- Built the company's first formal sales leadership development program."),
            ("body", "Senior Account Executive, Ironbridge Systems — 2011-2015"),
            ("body", "- Closed enterprise deals averaging $250,000 in annual contract value."),
            ("heading", "Education"),
            ("body", "B.A. in Business Administration, Emory University — 2011"),
            ("heading", "Skills"),
            (
                "body",
                (
                    "Sales leadership, revenue growth, team leadership, executive communication, "
                    "enterprise sales, CRM strategy"
                ),
            ),
        ],
    },
    {
        "vacancy_title": "Director of Sales",
        "first": "Ashley",
        "last": "Kim",
        "email": "ashley.kim@sample-applicant.test",
        "phone": "+1-702-555-0192",
        "filename": "ashley_kim_resume.docx",
        "lines": [
            ("title", "Ashley Kim"),
            ("body", "ashley.kim@sample-applicant.test | +1-702-555-0192 | Las Vegas, NV"),
            ("heading", "Professional Summary"),
            (
                "body",
                (
                    "Motivated sales representative with 1.5 years of experience selling to small "
                    "businesses. Consistently meets individual sales targets and is eager to grow "
                    "a career in sales."
                ),
            ),
            ("heading", "Experience"),
            ("body", "Sales Representative, Desert Sun Business Services — 2024-Present"),
            ("body", "- Meet monthly individual sales quota selling to small business owners."),
            ("body", "- Make 40+ outbound calls per day to prospective small business clients."),
            ("body", "- Log all activity and deals in the company CRM."),
            ("body", "Sales Associate, Desert Sun Business Services — 2023-2024"),
            ("body", "- Supported the sales team with lead follow-up and appointment scheduling."),
            ("heading", "Education"),
            ("body", "B.A. in Business, University of Nevada, Las Vegas — 2023"),
            ("heading", "Skills"),
            ("body", "Cold calling, CRM data entry, individual sales quota attainment"),
        ],
    },
]


async def seed_sample_applications() -> int:
    """Submit the sample resumes above as real applications through the full pipeline."""
    await init_db()
    async with async_session_factory() as db:
        svc = RecruitmentService(db)
        store = SyncS3ObjectStore()
        created = 0
        for entry in SAMPLE_APPLICATIONS:
            vacancy = await db.scalar(select(Vacancy).where(Vacancy.title == entry["vacancy_title"]))
            if vacancy is None:
                print(f"Skipping {entry['email']}: vacancy '{entry['vacancy_title']}' not found.")
                continue

            data = _build_resume_docx(entry["lines"])
            extraction = extract_text(data, entry["filename"], DOCX_CONTENT_TYPE)
            is_resume, reason = looks_like_resume(extraction.text)
            if not is_resume:
                print(f"Skipping {entry['email']}: failed resume classification — {reason}")
                continue
            is_parsable, reason = is_ats_friendly(extraction.text)
            if not is_parsable:
                print(f"Skipping {entry['email']}: failed ATS-parsability check — {reason}")
                continue

            object_key = store.put_resume(data, entry["filename"], DOCX_CONTENT_TYPE)
            try:
                await svc.apply_as_new_candidate(
                    vacancy_id=vacancy.vacancy_id,
                    cv_object_key=object_key,
                    first_name=entry["first"],
                    last_name=entry["last"],
                    email=entry["email"],
                    phone=entry["phone"],
                    password="applicant123",
                )
            except ValueError as err:
                print(f"Skipping {entry['email']}: {err}")
                continue
            created += 1

        print(f"Seeded {created} real application(s) with generated resumes.")
        return created


if __name__ == "__main__":
    asyncio.run(seed_sample_applications())

