from datetime import date

PAGES = [
    dict(slug="water-levels", label="Water levels", nav="primary",
         title="Flood Water Levels in Barangay Kauswagan", h1="Flood water levels in Barangay Kauswagan",
         description="Check the latest flood water level readings in Barangay Kauswagan from HydroHomie sensors.",
         intro="Latest sensor readings for Barangay Kauswagan will appear here.",
         placeholder="Live readings, status per zone and a last-updated time will be added in a later step."),

    dict(slug="alerts-events", label="Alerts & Events", nav="primary",
         title="Flood Alerts and Events History", h1="Flood alerts and events",
         description="Browse flood alerts and past flood events in Barangay Kauswagan, with dates and affected areas.",
         intro="Recent alerts and flood events in the barangay.",
         placeholder="A list of alerts and events will be added in a later step."),

    dict(slug="announcements", label="Announcements", nav="primary",
         title="Barangay Flood Announcements", h1="Barangay flood announcements",
         description="Read the latest announcements from barangay officials about flooding, advisories and community activities.",
         intro="News and advisories from barangay officials.",
         placeholder="Published announcements will appear here."),

    dict(slug="flood-map", label="Flood map", nav="primary",
         title="Flood Map of Barangay Kauswagan", h1="Flood map of Barangay Kauswagan",
         description="View the map of Barangay Kauswagan with sensor locations and flood-prone areas.",
         intro="See where sensors are placed and which areas are at risk.",
         placeholder="The interactive map will be added in a later step."),

    dict(slug="safety-guide", label="Safety guide", nav="primary",
         title="Flood Safety Guide: Before, During, After", h1="Flood safety guide",
         description="Simple steps to stay safe before, during and after a flood in Barangay Kauswagan.",
         intro="What to do before, during and after a flood.",
         placeholder="Safety steps will be written and reviewed with barangay officials."),

    dict(slug="evacuation", label="Evacuation centers", nav="footer",
         title="Evacuation Centers and Routes", h1="Evacuation centers and routes",
         description="Find evacuation centers and safe routes for residents of Barangay Kauswagan.",
         intro="Where to go when an evacuation is announced.",
         placeholder="Official evacuation center names and addresses must be supplied by the barangay."),

    dict(slug="hotlines", label="Emergency hotlines", nav="footer",
         title="Emergency Hotlines for Floods", h1="Emergency hotlines",
         description="Emergency hotline numbers for flood response in Barangay Kauswagan.",
         intro="Who to call in an emergency.",
         placeholder="Verified hotline numbers must be supplied by the barangay. Do not publish unverified numbers."),

    dict(slug="how-alerts-work", label="How alerts work", nav="footer",
         title="How Flood Alerts Work", h1="How flood alerts work",
         description="Learn how HydroHomie sensors detect rising water and how residents receive SMS alerts.",
         intro="From sensor reading to a text message on your phone.",
         placeholder="An explanation and the SMS sign-up form will be added in a later step."),

    dict(slug="reports", label="Reports", nav="footer",
         title="Flood Reports and Summaries", h1="Flood reports",
         description="Summaries of past flood events and water level trends in Barangay Kauswagan.",
         intro="Summaries of past events. Personal information is never shown.",
         placeholder="Summary reports will be added in a later step."),

    dict(slug="faq", label="FAQ", nav="footer",
         title="Flood Monitoring FAQ", h1="Frequently asked questions",
         description="Answers to common questions about HydroHomie flood monitoring and alerts.",
         intro="Quick answers to common questions.",
         placeholder="Questions and answers will be added in a later step."),

    dict(slug="about", label="About", nav="footer",
         title="About the Project", h1="About HydroHomie",
         description="HydroHomie is a flood monitoring and alert system for Barangay Kauswagan.",
         intro="What HydroHomie is and who is behind it.",
         placeholder="Team and project details will be added here."),

    dict(slug="contact", label="Contact", nav="footer",
         title="Contact and Feedback", h1="Contact us",
         description="Contact the HydroHomie team with questions or feedback about flood monitoring in Barangay Kauswagan.",
         intro="Questions or feedback? Reach the HydroHomie team.",
         placeholder=""),

    dict(slug="privacy", label="Privacy", nav="footer",
         title="Privacy Policy", h1="Privacy policy",
         description="How HydroHomie handles personal information, including phone numbers used for SMS alerts.",
         intro="How we handle your information.",
         placeholder="The full policy will be written before SMS sign-up goes live."),
]

PAGES_BY_SLUG = {p["slug"]: p for p in PAGES}
PRIMARY_NAV = [p for p in PAGES if p["nav"] == "primary"]
FOOTER_NAV = [p for p in PAGES if p["nav"] == "footer"]
LASTMOD = {
    slug: date(2026, 11, 23)
    for slug in [
        "safety-guide", "evacuation", "hotlines", "how-alerts-work",
        "faq", "about", "contact", "privacy",
    ]
}

RELATED = {
    "water-levels": ["flood-map", "alerts-events"],
    "alerts-events": ["how-alerts-work", "safety-guide"],
    "announcements": ["alerts-events", "hotlines"],
    "flood-map": ["evacuation", "water-levels"],
    "safety-guide": ["evacuation", "hotlines"],
    "evacuation": ["flood-map", "hotlines"],
    "hotlines": ["safety-guide", "contact"],
    "how-alerts-work": ["faq", "privacy"],
    "reports": ["alerts-events", "water-levels"],
    "faq": ["how-alerts-work", "contact"],
    "about": ["how-alerts-work", "contact"],
    "contact": ["faq", "hotlines"],
    "privacy": ["how-alerts-work", "contact"],
}

REDIRECTS = {
    "/home/": "/",
    "/index.html": "/",
    "/map/": "/flood-map/",
    "/alerts/": "/alerts-events/",
    "/events/": "/alerts-events/",
    "/water-level/": "/water-levels/",
    "/safety/": "/safety-guide/",
    "/evacuation-centers/": "/evacuation/",
    "/emergency-hotlines/": "/hotlines/",
    "/sms/": "/how-alerts-work/",
}

HOME_OG_TITLE = "Flood monitoring and alerts for Barangay Kauswagan"
HOME_DESCRIPTION = "HydroHomie monitors flood water levels in Barangay Kauswagan and sends alerts so residents can stay safe."