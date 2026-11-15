"""Seed a demo database (offline - no TMDB key needed): 5 demo users, 11 films with plots, a club, a poll, reviews.

    python -m scripts.seed_demo            (uses DATABASE_URL, default sqlite:///./cinelog.db)

Logins (password cinelog123): admin@cinelog.dev, mod@cinelog.dev, convener@cinelog.dev, critic@cinelog.dev, viewer@cinelog.dev,
pat@cinelog.dev (a viewer with a critic application waiting for a moderator)
TMDB ids below are the real ones, so a later TMDB sync enriches these rows instead of duplicating them.
"""
from __future__ import annotations

from sqlalchemy import select

from app.config import Settings
from app.main import create_app
import datetime as dt

from app.gamification import award
from app.models import (AspectRating, Club, ClubMember, ClubThread, ClubWatchlist, CriticApplication, CriticPick, DiaryEntry, Film, FilmList,
                        FilmListItem, Follow, Like, Poll, PollOption, Review, ThreadReply, User, UserRole, Vote, Watchalong,
                        WatchalongRsvp, WatchGoal, WatchlistItem)
from app.security import hash_password
from app.services import jobs
from app.services.catalog import set_plot, upsert_tmdb_film
from app.services.reviews import scan_review

FILMS = [
    (238, "The Godfather", "1972-03-24", ["Crime", "Drama"], [("Marlon Brando", "Vito Corleone"), ("Al Pacino", "Michael Corleone"), ("James Caan", "Sonny Corleone"), ("Robert Duvall", "Tom Hagen"), ("Diane Keaton", "Kay Adams")],
     "Vito Corleone, head of a New York crime family, is shot by rivals after he refuses to enter the narcotics trade. His youngest son Michael, a war hero who wants no part of the family business, murders the corrupt police captain McCluskey and the gangster Sollozzo and flees to Sicily. Sonny is gunned down at a tollbooth. Vito dies of a heart attack in his garden after Michael returns and takes over the family. During the baptism of his nephew Michael has the heads of the rival families killed and lies to his wife Kay about it."),
    (745, "The Sixth Sense", "1999-08-06", ["Thriller", "Mystery"], [("Bruce Willis", "Malcolm Crowe"), ("Haley Joel Osment", "Cole Sear"), ("Toni Collette", "Lynn Sear")],
     "Child psychologist Malcolm Crowe tries to help Cole Sear, a frightened boy who tells him that he sees dead people. Malcolm slowly believes the boy and helps the ghosts finish their unfinished business. In the final scene Malcolm realises that he was shot by a former patient at the start of the story and has been a ghost himself all along. His wife never answered him because she could not see him."),
    (550, "Fight Club", "1999-10-15", ["Drama"], [("Edward Norton", "The Narrator"), ("Brad Pitt", "Tyler Durden"), ("Helena Bonham Carter", "Marla Singer")],
     "An insomniac office worker meets the soap salesman Tyler Durden and together they start an underground fighting club. The club grows into Project Mayhem, a group that plans to destroy the credit card companies. The narrator discovers that Tyler Durden is his own split personality. He shoots himself through the cheek to kill Tyler and the buildings collapse while he holds Marla's hand."),
    (597, "Titanic", "1997-12-19", ["Drama", "Romance"], [("Leonardo DiCaprio", "Jack Dawson"), ("Kate Winslet", "Rose DeWitt Bukater"), ("Billy Zane", "Cal Hockley")],
     "Rose, a young woman engaged to the wealthy Cal Hockley, falls in love with the poor artist Jack Dawson aboard the Titanic. The ship hits an iceberg and sinks. Jack saves Rose by helping her onto a floating door, but there is no room for him and Jack dies of hypothermia in the freezing water. Years later the old Rose drops the Heart of the Ocean diamond into the sea."),
    (155, "The Dark Knight", "2008-07-18", ["Action", "Crime"], [("Christian Bale", "Bruce Wayne"), ("Heath Ledger", "The Joker"), ("Aaron Eckhart", "Harvey Dent"), ("Maggie Gyllenhaal", "Rachel Dawes")],
     "Batman, Lieutenant Gordon and the district attorney Harvey Dent fight the mob in Gotham, until the Joker arrives and forces the city into chaos. The Joker kills Rachel Dawes in an explosion. Harvey Dent is burned, turns into Two-Face and goes on a killing spree. Batman kills Two-Face to save Gordon's family and takes the blame for the murders so that the city can keep believing in Dent."),
    (27205, "Inception", "2010-07-16", ["Sci-Fi", "Action"], [("Leonardo DiCaprio", "Dom Cobb"), ("Joseph Gordon-Levitt", "Arthur"), ("Elliot Page", "Ariadne"), ("Cillian Murphy", "Robert Fischer")],
     "Dom Cobb steals secrets from people's dreams and is hired to plant an idea in the mind of Robert Fischer. The team goes through three dream levels while Cobb's dead wife Mal sabotages the job. Cobb lets go of Mal, Fischer accepts the idea and Cobb returns to his children. In the last shot Cobb spins his totem top and walks away before we see if it falls, so we never learn if he is still dreaming."),
    (496243, "Parasite", "2019-05-30", ["Thriller", "Drama"], [("Song Kang-ho", "Kim Ki-taek"), ("Choi Woo-shik", "Kim Ki-woo"), ("Park So-dam", "Kim Ki-jung"), ("Lee Sun-kyun", "Park Dong-ik")],
     "The poor Kim family fakes qualifications to become the employees of the rich Park family. They get the old housekeeper Moon-gwang fired and discover that her husband Geun-sae has been hiding in a secret basement bunker. During a birthday party Geun-sae stabs Ki-jung, who dies. Ki-taek kills Mr. Park and hides in the basement himself. Ki-woo dreams of buying the house to free his father."),
    (157336, "Interstellar", "2014-11-07", ["Sci-Fi", "Drama"], [("Matthew McConaughey", "Cooper"), ("Anne Hathaway", "Brand"), ("Jessica Chastain", "Murph")],
     "A dying Earth sends the pilot Cooper through a wormhole to find a new home for humanity. Professor Brand secretly knew that his gravity equation could not be solved and that Plan A was never possible. Cooper falls into the black hole Gargantua, ends up inside a tesseract and sends the data to his daughter Murph through her bookshelf and a wristwatch. Murph solves the equation and Cooper wakes up near Saturn."),
    (360814, "Dangal", "2016-12-23", ["Drama", "Sport"], [("Aamir Khan", "Mahavir Singh Phogat"), ("Fatima Sana Shaikh", "Geeta Phogat"), ("Sanya Malhotra", "Babita Kumari")],
     "Former wrestler Mahavir Singh Phogat trains his daughters Geeta and Babita to become wrestlers. Geeta moves to the national academy and loses to her father's methods for a while. In the Commonwealth Games final Geeta is locked out of her father's reach, he is locked in a room, and she wins the gold medal by following his old advice."),
    (20453, "3 Idiots", "2009-12-25", ["Comedy", "Drama"], [("Aamir Khan", "Rancho"), ("R. Madhavan", "Farhan Qureshi"), ("Sharman Joshi", "Raju Rastogi"), ("Kareena Kapoor", "Pia")],
     "Farhan and Raju search for their old friend Rancho, who vanished after college. They discover that Rancho was really the servant's son Chhote who studied under the name of the rich boy Ranchhoddas. The real Phunsukh Wangdu is a famous scientist in Ladakh who runs a school. Chatur loses the bet and Rancho marries Pia."),
    (76341, "Mad Max: Fury Road", "2015-05-15", ["Action", "Sci-Fi"], [("Tom Hardy", "Max Rockatansky"), ("Charlize Theron", "Imperator Furiosa"), ("Nicholas Hoult", "Nux")],
     "Furiosa escapes the tyrant Immortan Joe with his five wives and Max is dragged into the chase. They reach the Green Place and find it destroyed, so they turn back to take the Citadel. Nux sacrifices himself to block the pursuing rig and Immortan Joe is killed when Furiosa tears off his breathing mask. Furiosa becomes the new ruler of the Citadel."),
]

# spoiler-free one-liners shown on film pages (the plots above are only used as hidden matching context)
OVERVIEWS = {
    "The Godfather": "The ageing head of a New York crime family hands his empire to a reluctant son.",
    "The Sixth Sense": "A child psychologist takes on a frightened boy who says he can see the dead.",
    "Fight Club": "An insomniac office worker and a soap salesman start an underground club with very strict rules.",
    "Titanic": "A society girl and a penniless artist fall in love aboard the most famous ship in the world.",
    "The Dark Knight": "Gotham's masked vigilante faces a criminal who only wants to watch the city burn.",
    "Inception": "A thief who steals secrets from dreams is offered one last job: planting an idea instead.",
    "Parasite": "A struggling family talks its way, one job at a time, into a wealthy household.",
    "Interstellar": "With Earth failing, a pilot leaves his children to search for a new home among the stars.",
    "Dangal": "A former wrestler trains his daughters to chase the gold medal he never won.",
    "3 Idiots": "Two friends go looking for the classmate who taught them to think for themselves.",
    "Mad Max: Fury Road": "In a desert wasteland, a drifter and a rebel driver flee a tyrant in one long chase.",
}
RUNTIMES = {"The Godfather": 175, "The Sixth Sense": 107, "Fight Club": 139, "Titanic": 194, "The Dark Knight": 152, "Inception": 148,
            "Parasite": 132, "Interstellar": 169, "Dangal": 161, "3 Idiots": 170, "Mad Max: Fury Road": 120}

REVIEWS = [
    ("viewer@cinelog.dev", "The Sixth Sense", "Brilliantly directed, the pacing is patient and the acting from the kid is outstanding. The twist where Malcolm was a ghost all along is the best part, I did not see it coming."),
    ("critic@cinelog.dev", "Inception", "A dazzling heist inside a dream. The score is huge and the visuals are unforgettable. Whether the top keeps spinning at the end is left for you to decide, which I loved."),
    ("viewer@cinelog.dev", "Titanic", "Gorgeous production design and a moving score. Jack dies in the freezing water while Rose floats on the door, and I still cried."),
    ("critic@cinelog.dev", "Parasite", "Sharp, funny and terrifying. The class satire works because every performance is precise. Go in knowing as little as possible."),
]


def _seed_engagement(app) -> None:
    """Phase 12 demo data: a year of viewing (for Year in Review and recommendations), a goal, critic picks, a pending critic
    application, and a closed poll with a past watch-along (for the club's analytics). Safe to run again."""
    from app.services.polls import finalize_poll
    with app.state.db.session() as s:
        if s.scalar(select(CriticPick.user_id)):
            return
        u = {e: s.scalar(select(User).where(User.email == e + "@cinelog.dev")) for e in ("viewer", "critic", "convener", "mod")}
        fb = {f.title: f for f in s.scalars(select(Film))}
        today = dt.date.today()
        # a year of viewing for the viewer: spread over the past months so the charts have a shape
        history = [("Fight Club", 4.5, 300, "Theatre"), ("Dangal", 4, 250, "OTT"), ("The Dark Knight", 5, 210, "IMAX"), ("Mad Max: Fury Road", 4, 160, "OTT"),
                   ("3 Idiots", 5, 120, "OTT"), ("The Godfather", 4.5, 95, "OTT"), ("Interstellar", 5, 60, "IMAX"), ("The Dark Knight", 5, 35, "Theatre")]
        for title, stars, ago, fmt in history:
            d = today - dt.timedelta(days=ago)
            if d.year != today.year:
                d = dt.date(today.year, 1, 1) + dt.timedelta(days=(ago * 7) % 200)
            s.add(DiaryEntry(user_id=u["viewer"].id, film_id=fb[title].id, watched_on=min(d, today), stars=stars, format=fmt, rewatch=(title == "The Dark Knight" and ago == 35)))
        s.add(WatchGoal(user_id=u["viewer"].id, year=today.year, target=24))
        # critic picks: what the critic role is for
        s.add(CriticPick(user_id=u["critic"].id, film_id=fb["Parasite"].id, blurb="Go in knowing nothing. Every shot is doing two jobs."))
        s.add(CriticPick(user_id=u["critic"].id, film_id=fb["Inception"].id, blurb="Still the best big-screen puzzle of its decade."))
        # a pending critic application, so the moderator's Critic applications tab has something to decide
        p = User(email="pat@cinelog.dev", display_name="Pat Pending", password_hash=hash_password("cinelog123"))
        p.roles = [UserRole(role="viewer")]
        s.add(p); s.flush()
        for k, title in enumerate(["The Godfather", "Parasite", "Inception", "Titanic", "3 Idiots"]):
            s.add(DiaryEntry(user_id=p.id, film_id=fb[title].id, watched_on=today - dt.timedelta(days=k + 1), stars=[4.5, 5, 4, 3.5, 4][k]))
        s.add(Review(user_id=p.id, film_id=fb["Parasite"].id, state="published", text="Sharp, funny and terrifying: the staging does the talking.",
                     segments_json='[{"idx": 0, "text": "Sharp, funny and terrifying: the staging does the talking.", "blurred": false, "risk": 0.05, "reasons": []}]'))
        s.add(CriticApplication(user_id=p.id, statement="I run the film column of my college magazine and have reviewed twenty festival films over the last two years.",
                                links="https://example.com/pat-writes-about-film"))
        # a closed poll and the watch-along it led to, in the past, with RSVPs and votes
        club = s.scalar(select(Club))
        poll = Poll(club_id=club.id, title="Last month's pick", state="open", created_by=u["convener"].id)
        poll.options = [PollOption(film_id=fb[t].id) for t in ("Parasite", "Inception", "3 Idiots")]
        s.add(poll); s.flush()
        for who, k in (("viewer", 0), ("critic", 0), ("convener", 0), ("mod", 1)):
            s.add(Vote(poll_id=poll.id, user_id=u[who].id, option_id=poll.options[k].id))
        s.flush()
        finalize_poll(s, poll)
        past = Watchalong(club_id=club.id, film_id=fb["Parasite"].id, poll_id=poll.id, created_by=u["convener"].id,
                          starts_at=dt.datetime.utcnow() - dt.timedelta(days=9))
        s.add(past); s.flush()
        for who in ("viewer", "critic", "convener"):
            s.add(WatchalongRsvp(watchalong_id=past.id, user_id=u[who].id))
        later = Watchalong(club_id=club.id, film_id=fb["Mad Max: Fury Road"].id, created_by=u["convener"].id,
                           starts_at=(dt.datetime.utcnow() + dt.timedelta(days=12)).replace(hour=19, minute=0, second=0, microsecond=0))
        s.add(later)
        s.flush()
        for x in list(u.values()) + [p]:
            award(s, x.id)


def main() -> None:
    app = create_app(Settings(start_workers=False))
    with app.state.db.session() as s:
        for email, name, roles in [("admin@cinelog.dev", "Alex Admin", ["viewer", "admin"]),
                                   ("mod@cinelog.dev", "Mo Moderator", ["viewer", "moderator"]),
                                   ("convener@cinelog.dev", "Cleo Convener", ["viewer", "convener"]),
                                   ("critic@cinelog.dev", "Cam Critic", ["viewer", "critic"]),
                                   ("viewer@cinelog.dev", "Vic Viewer", ["viewer"])]:
            if not s.scalar(select(User).where(User.email == email)):
                u = User(email=email, display_name=name, password_hash=hash_password("cinelog123"))
                u.roles = [UserRole(role=r) for r in roles]
                s.add(u)
        s.flush()
        for tid, title, rd, genres, cast, plot in FILMS:
            f = upsert_tmdb_film(s, {"id": tid, "title": title, "release_date": rd, "overview": OVERVIEWS.get(title, ""),
                                     "runtime": RUNTIMES.get(title),
                                     "popularity": 50.0, "genres": [{"name": g} for g in genres],
                                     "credits": {"cast": [{"name": a, "character": c} for a, c in cast]}})
            if not f.plot_checked:
                set_plot(s, f, plot, "seed")
        s.flush()
        conv = s.scalar(select(User).where(User.email == "convener@cinelog.dev"))
        if not s.scalar(select(Club.id)):
            club = Club(name="Campus Film Society", description="Friday night screenings", is_public=True)
            s.add(club); s.flush()
            s.add(ClubMember(club_id=club.id, user_id=conv.id, role="convener"))
            for u in s.scalars(select(User).where(User.email.in_(["viewer@cinelog.dev", "critic@cinelog.dev"]))):
                s.add(ClubMember(club_id=club.id, user_id=u.id, role="member"))
            films = list(s.scalars(select(Film).where(Film.title.in_(["Inception", "Parasite", "Interstellar"]))))
            for f in films:
                s.add(ClubWatchlist(club_id=club.id, film_id=f.id, added_by=conv.id))
            p = Poll(club_id=club.id, title="Friday's screening", state="draft", created_by=conv.id)
            p.options = [PollOption(film_id=f.id) for f in films]
            s.add(p)
        ids = []
        for email, title, text in REVIEWS:
            u = s.scalar(select(User).where(User.email == email))
            f = s.scalar(select(Film).where(Film.title == title))
            if not s.scalar(select(Review.id).where(Review.user_id == u.id, Review.film_id == f.id)):
                r = Review(user_id=u.id, film_id=f.id, text=text, state="pending_scan")
                s.add(r); s.flush(); ids.append(r.id)
        # a little activity so the diary, feed, radar and "similar tastes" screens have something to show
        if not s.scalar(select(DiaryEntry.id)):
            today = dt.date.today()
            people = {e: s.scalar(select(User).where(User.email == e + "@cinelog.dev")) for e in ("viewer", "critic", "convener", "mod")}
            titles = [t for _, t, *_ in FILMS]
            film_by = {f.title: f for f in s.scalars(select(Film).where(Film.title.in_(titles)))}
            plan = {"viewer": [(0, 4.5), (1, 5), (2, 4), (3, 3.5), (5, 4.5), (6, 5), (8, 4)],
                    "critic": [(0, 5), (1, 4.5), (2, 4.5), (3, 3), (5, 5), (6, 4.5), (7, 4)],
                    "convener": [(0, 4), (1, 4), (2, 3.5), (5, 4.5), (6, 5), (9, 4.5), (10, 4)],
                    "mod": [(4, 5), (7, 4.5), (10, 4.5)]}
            for who, rows in plan.items():
                u = people[who]
                for k, (i, stars) in enumerate(rows):
                    f = film_by[titles[i]]
                    s.add(DiaryEntry(user_id=u.id, film_id=f.id, watched_on=today - dt.timedelta(days=k * (1 if who == "viewer" and k < 4 else 3)),
                                     format=["OTT", "Theatre", "OTT", "IMAX"][k % 4], stars=stars))
                    for j, a in enumerate(("story", "acting", "visuals", "music", "pacing")):
                        v = max(0.5, min(5, stars + [0, 0.5, -0.5, 0, -1][(j + i) % 5]))
                        s.merge(AspectRating(user_id=u.id, film_id=f.id, aspect=a, value=v))
            s.add(Follow(follower_id=people["viewer"].id, followee_id=people["critic"].id))
            s.add(Follow(follower_id=people["viewer"].id, followee_id=people["convener"].id))
            s.add(Follow(follower_id=people["critic"].id, followee_id=people["viewer"].id))
            for t in ("Interstellar", "Mad Max: Fury Road", "3 Idiots"):
                s.merge(WatchlistItem(user_id=people["viewer"].id, film_id=film_by[t].id))
    jobs.refit_shield_space(app)
    with app.state.db.session() as s:
        app.state.search.rebuild(s)
    for rid in ids:
        scan_review(app, rid)
    with app.state.db.session() as s:
        if not s.scalar(select(FilmList.id)):
            u = {e: s.scalar(select(User).where(User.email == e + "@cinelog.dev")) for e in ("viewer", "critic", "convener", "mod", "admin")}
            fb = {f.title: f for f in s.scalars(select(Film))}
            lists = [("critic", "Twists you should not read about first", "Go in blind. Every one of these rewards it.",
                      ["The Sixth Sense", "Fight Club", "Parasite", "Inception", "The Dark Knight"]),
                     ("convener", "Friday night crowd-pleasers", "Proven in a lecture hall with bad speakers.",
                      ["3 Idiots", "Dangal", "Mad Max: Fury Road", "Inception", "Interstellar"]),
                     ("viewer", "Big feelings, bigger runtimes", "Bring snacks.", ["Titanic", "Interstellar", "The Godfather", "Dangal"])]
            made = []
            for who, title, desc, films in lists:
                fl = FilmList(user_id=u[who].id, title=title, description=desc)
                fl.items = [FilmListItem(film_id=fb[t].id, position=k) for k, t in enumerate(films)]
                s.add(fl); s.flush(); made.append(fl)
            for who, i in (("viewer", 0), ("convener", 0), ("mod", 0), ("critic", 1), ("viewer", 1), ("critic", 2)):
                s.add(Like(user_id=u[who].id, kind="list", target_id=made[i].id))
            for r in s.scalars(select(Review).where(Review.state == "published")):
                for who in ("convener", "mod", "viewer", "critic"):
                    if u[who].id != r.user_id and (r.id + u[who].id) % 3:
                        s.add(Like(user_id=u[who].id, kind="review", target_id=r.id))
            club = s.scalar(select(Club))
            t1 = ClubThread(club_id=club.id, user_id=u["convener"].id, tag="Welcome", title="Newcomers: say hi and name your comfort film",
                            body="Pinned in spirit. Tell us what you rewatch when term gets heavy.")
            t1.replies = [ThreadReply(user_id=u["viewer"].id, body="3 Idiots, every exam season, without fail."),
                          ThreadReply(user_id=u["critic"].id, body="Mad Max: Fury Road. It is basically a nap for my brain.")]
            t2 = ClubThread(club_id=club.id, user_id=u["critic"].id, tag="Hot take", title="The second act is where great films are made",
                            body="Openings get the hype. The middle is where a director shows their hand.")
            s.add_all([t1, t2]); s.flush()
            for who, t in (("viewer", t1), ("critic", t1), ("viewer", t2), ("convener", t2)):
                s.add(Like(user_id=u[who].id, kind="thread", target_id=t.id))
            w = Watchalong(club_id=club.id, film_id=fb["Interstellar"].id, created_by=u["convener"].id,
                           starts_at=(dt.datetime.utcnow() + dt.timedelta(days=5)).replace(hour=14, minute=30, second=0, microsecond=0))
            s.add(w); s.flush()
            s.add(WatchalongRsvp(watchalong_id=w.id, user_id=u["critic"].id))
            s.flush()
            for x in u.values():
                award(s, x.id)
    _seed_engagement(app)
    print(f"seeded {len(FILMS)} films, 5 demo users (password cinelog123), 1 club, {len(ids)} reviews")


if __name__ == "__main__":
    main()
