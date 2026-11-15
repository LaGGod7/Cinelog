"""Fill the database with made-up ("garbage") reviews and run every one through the real Spoiler Shield, then score it.

    python -m scripts.seed_spoiler_test            (uses DATABASE_URL and MODEL_DIR like the site does)
    python -m scripts.seed_spoiler_test --clean    (removes the made-up users and their reviews again)

Needs the demo films (python -m scripts.seed_demo); runs it for you if they are missing. The made-up users are
garbage01@cinelog.dev ... (password cinelog123, role viewer); their reviews show up on the film pages like real ones.
Each case has a label written by hand, so the report says where the shield is right and where it is not. The sample is small
and my own wording, so read it as a smoke test and a way to look at mistakes, not as a measurement of accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import delete, select

from app.config import Settings
from app.main import create_app
from app.models import Film, Review, User, UserRole
from app.security import hash_password
from app.services.reviews import review_view, scan_review

# (film, kind, text, [substrings of the sentences that really give the story away])
#   clean  : no giveaway          spoiler : gives away the ending / twist       mixed : mostly fine, one or two giveaway sentences
#   tagged : writer hid it with ||..||                                          vague : mentions "a twist" without saying what (not scored)
CASES = [
    # ---- clean: praise, craft, cast, set-up only
    ("The Godfather", "clean", "A masterclass in patient storytelling. The cinematography is dark and warm, and every scene feels like a painting. Brando is unforgettable.", []),
    ("The Sixth Sense", "clean", "Wonderful acting from the young lead. The mood is creepy without cheap jump scares and the score is restrained. Highly recommended for a quiet night.", []),
    ("Fight Club", "clean", "Sharp, angry and very funny in places. Edward Norton and Brad Pitt have great chemistry. The editing is restless in the best way.", []),
    ("Titanic", "clean", "Huge scale and gorgeous costumes. The first half is a charming romance and the second half is pure spectacle. Kate Winslet is wonderful.", []),
    ("The Dark Knight", "clean", "The pacing is relentless and the villain is terrifying. Hans Zimmer's score keeps the tension up for nearly three hours. A benchmark for superhero films.", []),
    ("Inception", "clean", "Dazzling visuals and a score that rattles your chest. The cast is excellent and the action scenes are inventive. You will want to watch it twice.", []),
    ("Parasite", "clean", "Funny, tense and beautifully shot. The house itself is a character. Go in knowing as little as possible and trust the director.", []),
    ("Interstellar", "clean", "An emotional space epic with a thundering organ score. The docking scene had me gripping my seat. Matthew McConaughey gives a heartfelt performance.", []),
    ("Dangal", "clean", "Inspiring and warm. Aamir Khan disappears into the role and the wrestling scenes feel real. Bring tissues and a friend.", []),
    ("3 Idiots", "clean", "Hilarious and heartfelt, with songs that stay in your head. The college setting feels authentic. I laughed, I cried, I called my old friends.", []),
    ("Mad Max: Fury Road", "clean", "Two hours of pure kinetic cinema. The practical stunts are astonishing and the world feels lived in. Charlize Theron owns the screen.", []),
    ("Inception", "clean", "Without giving anything away, the idea of stealing secrets from dreams is brilliant. Leonardo DiCaprio leads a strong team. The hallway fight is a highlight.", []),
    ("Titanic", "clean", "It is about a rich girl and a poor artist who meet on a ship. The setup is simple and works. The sets are amazing.", []),
    ("Parasite", "clean", "A poor family befriends a wealthy one and things get complicated. The performances are razor sharp and the tone shifts constantly.", []),
    ("The Godfather", "clean", "Al Pacino, Marlon Brando and James Caan are all fantastic. The wedding opening is one of the best in cinema. The dialogue is endlessly quotable.", []),
    ("Interstellar", "clean", "I liked the practical effects and the sound design. The science talk is heavy at times but the father-daughter bond holds it together.", []),
    # ---- spoiler: says the ending / twist outright (uses the story's own words)
    ("The Sixth Sense", "spoiler", "Great film. The twist is that Malcolm was dead the whole time and he is a ghost himself. His wife could not see him at the end.", ["dead", "ghost", "could not see him"]),
    ("Fight Club", "spoiler", "Tyler Durden is the narrator's split personality. He shoots himself in the cheek to get rid of Tyler at the end.", ["split personality", "shoots himself"]),
    ("Titanic", "spoiler", "Jack dies of hypothermia in the freezing water because the door only holds one person. Old Rose drops the diamond into the sea.", ["dies", "diamond"]),
    ("The Dark Knight", "spoiler", "The Joker kills Rachel in the explosion and Harvey Dent becomes Two-Face. Batman takes the blame for the murders at the end.", ["kills Rachel", "Two-Face", "takes the blame"]),
    ("Inception", "spoiler", "In the last shot Cobb spins the top and walks away before it falls, so we never learn if he is still dreaming. His wife Mal was dead all along.", ["spins the top", "Mal"]),
    ("Parasite", "spoiler", "The housekeeper's husband has been hiding in the secret basement bunker. Geun-sae stabs Ki-jung at the party and Ki-taek kills Mr. Park.", ["basement", "stabs", "kills Mr. Park"]),
    ("Interstellar", "spoiler", "Cooper falls into the black hole and sends data to Murph through the bookshelf. Professor Brand lied about the equation being unsolvable.", ["black hole", "bookshelf", "lied"]),
    ("The Godfather", "spoiler", "Michael has the heads of the rival families killed during the baptism while lying to Kay. Sonny is gunned down at a tollbooth earlier.", ["baptism", "tollbooth"]),
    ("3 Idiots", "spoiler", "Rancho turns out to be the servant's son who studied under the rich boy's name. The real Phunsukh Wangdu is a scientist in Ladakh.", ["servant's son", "Ladakh"]),
    ("Mad Max: Fury Road", "spoiler", "Nux sacrifices himself to block the rig and Furiosa tears off Immortan Joe's mask to kill him. She becomes the ruler of the Citadel.", ["sacrifices himself", "mask", "ruler"]),
    ("Dangal", "spoiler", "In the final Geeta wins the gold medal after her father is locked in a room and she follows his old advice.", ["gold medal", "locked in a room"]),
    # ---- spoiler, paraphrased: the giveaway is said in different words (hard for any word-based method)
    ("The Sixth Sense", "spoiler", "Honestly the final reveal that the doctor had actually passed away before the story even started floored me.", ["passed away"]),
    ("Fight Club", "spoiler", "The charismatic soap guy only exists inside the main character's head, which explains everything.", ["only exists inside"]),
    ("Titanic", "spoiler", "She survives on a piece of wood while he freezes to death in the sea. I was sobbing.", ["freezes to death"]),
    ("Parasite", "spoiler", "There is somebody living under the house all along, and the party ends in a bloodbath.", ["living under the house", "bloodbath"]),
    ("Inception", "spoiler", "The ending leaves it open whether the spinning toy ever stops, so he might still be asleep.", ["spinning toy"]),
    ("Interstellar", "spoiler", "The father ends up inside a five dimensional structure and talks to his child across time through the books.", ["five dimensional", "through the books"]),
    # ---- mixed: mostly fine with one giveaway sentence
    ("The Dark Knight", "mixed", "Heath Ledger is magnetic. Rachel dies in the explosion and it devastates Bruce. The score is superb and the Batpod chase is great.", ["Rachel dies"]),
    ("Titanic", "mixed", "The production design is incredible. Jack dies in the cold water while Rose lives on. The soundtrack is iconic. Winslet is terrific.", ["Jack dies"]),
    ("Mad Max: Fury Road", "mixed", "A wild ride from the first minute. Furiosa kills Immortan Joe by tearing off his breathing mask. The editing is the best of the decade.", ["Furiosa kills"]),
    ("Fight Club", "mixed", "Brilliant dialogue and a killer soundtrack. Tyler is just the narrator's alter ego, which is the whole point. Fincher directs with swagger.", ["alter ego"]),
    ("Dangal", "mixed", "Aamir Khan's transformation is impressive. Geeta wins the gold in the Commonwealth final. The songs are lively and the humour lands.", ["wins the gold"]),
    # ---- tagged by the writer
    ("Inception", "tagged", "Loved it. ||Cobb never learns if the top fell.|| The soundtrack is huge.", ["never learns"]),
    ("Parasite", "tagged", "Spectacular. ||The husband lives in the basement.|| Very funny first half.", ["basement"]),
    # ---- vague: hints at a twist without saying it (reported, not scored)
    ("The Sixth Sense", "vague", "That twist at the end is incredible, you will not see it coming. The last ten minutes made me rewatch the whole film.", []),
    ("Fight Club", "vague", "The ending is something else. I will not say more but it recontextualises everything before it.", []),
    ("Parasite", "vague", "The second half goes somewhere shocking. Watch it blind and thank me later.", []),
    ("Titanic", "vague", "The ending destroyed me, I was in tears for an hour afterwards.", []),
]


def clean_up(s) -> int:
    ids = list(s.scalars(select(User.id).where(User.email.like("garbage%@cinelog.dev"))))
    if ids:
        s.execute(delete(Review).where(Review.user_id.in_(ids)))
        s.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
        s.execute(delete(User).where(User.id.in_(ids)))
    return len(ids)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="remove the made-up users and their reviews, then stop")
    a = ap.parse_args(argv)
    app = create_app(Settings(start_workers=False))
    with app.state.db.session() as s:
        if a.clean:
            print(f"removed {clean_up(s)} made-up users and their reviews")
            return 0
        have_demo = s.scalar(select(Film.id).where(Film.title == "Parasite")) is not None
    if not have_demo:                       # (a separate app, started after the first one has let go of the database)
        from scripts import seed_demo
        print("demo films missing - running seed_demo first")
        seed_demo.main()
        app = create_app(Settings(start_workers=False))
    with app.state.db.session() as s:
        clean_up(s)
        films = {f.title: f.id for f in s.scalars(select(Film))}
        todo = []
        for i, (title, kind, text, spoilers) in enumerate(CASES, 1):
            u = User(email=f"garbage{i:02d}@cinelog.dev", display_name=f"Garbage Tester {i:02d}", password_hash=hash_password("cinelog123"))
            u.roles = [UserRole(role="viewer")]
            s.add(u); s.flush()
            r = Review(user_id=u.id, film_id=films[title], text=text, state="pending_scan")
            s.add(r); s.flush()
            todo.append((r.id, title, kind, text, spoilers))
    for rid, *_ in todo:
        scan_review(app, rid)

    st = app.state.shield.status()
    print(f"shield: ml={st['ml']} rnn={st['rnn']} {'(active)' if (st.get('rnn_meta') or {}).get('active') else '(not active)'}\n")
    tally = {k: {"n": 0, "blurred": 0, "ask": 0, "warn": 0, "shown": 0} for k in ("clean", "spoiler", "mixed", "tagged", "vague")}
    sp_hit = sp_total = fb = leaks = 0
    rows = []
    with app.state.db.session() as s:
        for rid, title, kind, text, spoilers in todo:
            r = s.get(Review, rid)
            segs = json.loads(r.segments_json)
            blurred = [g["text"] for g in segs if g["blurred"]]
            outcome = "BLURRED" if blurred else ("ASK-MOD" if r.uncertain else ("WARN" if r.warn else "shown"))
            t = tally[kind]; t["n"] += 1; t[{"BLURRED": "blurred", "ASK-MOD": "ask", "WARN": "warn", "shown": "shown"}[outcome]] += 1
            public = json.dumps(review_view(r, None)["segments"])       # what a stranger receives
            leaks += sum(b.strip() in public for b in blurred)
            note = ""
            if spoilers:
                hit = {k for k in spoilers if any(k.lower() in b.lower() for b in blurred)}
                sp_hit += len(hit); sp_total += len(spoilers)
                fb += sum(not any(k.lower() in b.lower() for k in spoilers) for b in blurred)
                note = f"giveaways hidden {len(hit)}/{len(spoilers)}"
            elif blurred and kind == "clean":
                note = "hid: " + " | ".join(b.strip()[:50] for b in blurred)
            ok = {"clean": outcome == "shown", "vague": None}.get(kind, outcome == "BLURRED" or None if outcome == "WARN" else outcome == "BLURRED")
            rows.append((("ok  " if ok else "----" if ok is False else "    "), kind, outcome, f"{title[:18]:18s}", text[:58].replace("\n", " "), note))
    for r in rows:
        print(f"{r[0]} {r[1]:7s} {r[2]:8s} {r[3]} {r[4]!r:62s} {r[5]}")
    c, sp, mx, tg, vg = (tally[k] for k in ("clean", "spoiler", "mixed", "tagged", "vague"))
    print("\nSUMMARY (hand-labelled, small sample)   flagged = blurred, sent to moderators, or labelled 'possible spoilers'")
    fl = lambda t: t["blurred"] + t["ask"] + t["warn"]  # noqa: E731
    print(f"  clean reviews left alone      {c['shown']}/{c['n']}   (blurred {c['blurred']}, to moderators {c['ask']}, labelled {c['warn']})")
    for name, t in (("spoiler", sp), ("mixed", mx), ("writer-tagged", tg)):
        print(f"  {name + ' reviews':29s} flagged {fl(t)}/{t['n']}   (blurred {t['blurred']}, to moderators {t['ask']}, labelled {t['warn']}, missed {t['shown']})")
    both = {k: sp[k] + mx[k] + tg[k] for k in ("n", "blurred", "ask", "warn", "shown")}
    print(f"  ALL spoiler-containing reviews: flagged {fl(both)}/{both['n']} = {fl(both) / both['n']:.0%}   (blurred {both['blurred']}/{both['n']} = {both['blurred'] / both['n']:.0%})")
    print(f"  vague 'there is a twist' ones flagged {fl(vg)}/{vg['n']}   (a judgement call, not scored)")
    print(f"  giveaway sentences hidden     {sp_hit}/{sp_total};  other sentences hidden in those reviews: {fb}")
    print(f"  blurred text visible to a stranger: {leaks}   (must be 0)")
    print("\nThe made-up reviews are now on the film pages. Remove them with:  python -m scripts.seed_spoiler_test --clean")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
