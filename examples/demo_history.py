"""Make a fake Brave History file, so you can try tabtrail without your own data.

    python examples/demo_history.py /tmp/tabtrail-demo/profile
"""
import pathlib, random, sqlite3, sys, time

THEMES = {  # theme: (host, subjects, weight toward the last 14 days)
    "rust": ("doc.rust-lang.org", ["ownership", "borrow checker", "lifetimes", "async await", "traits", "error handling", "iterators", "smart pointers"], 0.8),
    "bread": ("kingarthurbaking.com", ["sourdough starter", "bread hydration", "overnight proofing", "dutch oven loaf", "rye bread", "focaccia dough", "scoring a loaf", "feeding a starter"], 0.3),
    "cycling": ("cyclingweekly.com", ["bike chain cleaning", "road bike tyre pressure", "cycling cadence", "bike fit saddle height", "gravel bike routes", "disc brake bleeding", "tubeless tyre setup", "cycling base training"], 0.05),
    "space": ("nasa.gov", ["James Webb telescope", "exoplanet atmosphere", "Mars sample return", "black hole imaging", "Artemis moon mission", "Europa ocean", "neutron star merger", "Saturn rings age"], 0.5),
}
PAGES = ["{} explained", "A beginner guide to {}", "Common mistakes with {}", "{} in practice", "Deep dive: {}", "How {} works"]
SEARCHES = ["{}", "{} tutorial", "how does {} work", "best way to learn {}"]

def main(out: str) -> None:
    random.seed(0)
    dest = pathlib.Path(out); dest.mkdir(parents=True, exist_ok=True)
    (dest / "History").unlink(missing_ok=True)
    db = sqlite3.connect(dest / "History")
    db.executescript("""create table urls(id integer primary key, url text, title text);
        create table visits(id integer primary key, url int, visit_time int, transition int, visit_duration int);
        create table keyword_search_terms(url_id int, term text);
        create table context_annotations(visit_id integer primary key, total_foreground_duration int);""")
    n, now = 0, time.time()
    for host, subjects, recent in THEMES.values():
        for subject in subjects:
            rows = [(p.format(subject), None) for p in PAGES] + [(s.format(subject), s.format(subject)) for s in SEARCHES]
            for title, term in rows:
                n += 1
                db.execute("insert into urls values (?,?,?)", (n, f"https://{host if not term else 'search.brave.com'}/{n}", title.capitalize()))
                if term: db.execute("insert into keyword_search_terms values (?,?)", (n, term))
                days = random.uniform(0, 13) if random.random() < recent else random.uniform(15, 80)
                chromium_us = int((now - days * 86400 + 11644473600) * 1_000_000)
                seconds = random.randint(20, 600)
                db.execute("insert into visits values (?,?,?,?,?)", (n, n, chromium_us, 0, seconds * 1_000_000))
                db.execute("insert into context_annotations values (?,?)", (n, seconds * 1_000_000))
    db.commit(); db.close()
    print(f"{n} visits written to {dest / 'History'}")

if __name__ == "__main__":
    main(sys.argv[1])
