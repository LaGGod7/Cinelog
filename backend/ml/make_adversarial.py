"""Writes ml/gold_adversarial.json: reviews that GIVE AWAY the story without looking like it (and clean reviews that LOOK spoilery).

Written by hand (not generated), from the plots of the 11 demo films in scripts/seed_demo.py. Labels are mine, not human-verified.
kind  = "disguised"  the review gives away something from the second half of the film (spoiler)
        "hard_clean" the review contains spoiler-ish words or topics but gives nothing away (must NOT be flagged)
cat   = the disguise used, so the report can say WHICH tricks fool the shield.
"""
import json
import os

D = "disguised"
C = "hard_clean"
R = []


def add(film, kind, cat, text):
    R.append({"film": film, "kind": kind, "cat": cat, "text": text})


# ---------------------------------------------------------------- understatement / euphemism
for f, t in [
    ("Titanic", "Let's just say the guy on the poster doesn't make it to the end credits, and the cold water has a lot to do with it."),
    ("The Sixth Sense", "Let's just say the doctor's own situation turns out to be a lot more permanent than he realises."),
    ("The Godfather", "Let's just say the old man doesn't get to enjoy his tomatoes for very long once the youngest takes over."),
    ("The Dark Knight", "Let's just say Gotham's golden boy ends the film with a very different face than he started with."),
    ("Mad Max: Fury Road", "Let's just say the tyrant's breathing equipment is not the thing he walks away with."),
    ("Parasite", "Let's just say the birthday party in the garden is not remembered fondly by anyone who attended."),
    ("Interstellar", "Let's just say the famous professor was not entirely honest with everybody about what the equation could do."),
    ("Fight Club", "Let's just say the best friend turns out to be a lot closer to home than the narrator assumed, like inside his own skull."),
]:
    add(f, D, "euphemism", t)
# ---------------------------------------------------------------- Hinglish / transliteration
for f, t in [
    ("3 Idiots", "Last me pata chalta hai ki Rancho asli me ek servant ka beta tha, aur Ladakh me school chala raha hai. Full emotional ho gaya yaar."),
    ("Dangal", "Climax me Geeta ne gold jeet liya aur papa ko ek kamre me band kar diya tha, phir bhi unki sikhayi hui chaal kaam aayi. Rona aa gaya."),
    ("Titanic", "Jack to aakhir me mar jata hai, Rose ke paas door pe jagah thi lekin Jack ke liye nahi. Dil toot gaya bhai."),
    ("Fight Club", "Tyler Durden koi alag aadmi hai hi nahi, wo to hero ke dimaag ka hi dusra roop hai. Mind blown."),
    ("The Sixth Sense", "Doctor sahab khud pehle se hi mar chuke the, isiliye unki biwi unse baat hi nahi karti thi. Kya twist hai."),
    ("Mad Max: Fury Road", "Nux ne apni jaan de di truck ko rokne ke liye aur Furiosa ne Joe ka mask nochkar usse maar diya."),
]:
    add(f, D, "hinglish", t)
# ---------------------------------------------------------------- slang, typos, emoji, caps
for f, t in [
    ("Titanic", "jack ded at the end bruh 😭😭 that door was big enough for 2 smh"),
    ("The Dark Knight", "bro RACHEL DIES lmaooo and then harvey goes full 2face. gordons family almost got it too 💀"),
    ("Inception", "ngl the ending just cuts to black while the totem is still spinnin 🤯 u never find out if hes still dreaming"),
    ("Parasite", "dude the bunker guy under the house stabs the daughter at the party then the dad snaps n kills the rich guy. WILD"),
    ("The Godfather", "so micheal whacks the cop n the gangster in the restaurant then hides in sicily, sonny gets shot at the toll booth lol"),
    ("Mad Max: Fury Road", "NUX BLOWS HIMSELF UP to stop the rig. furiosa takes the citadel at the end. I CRIED 😭"),
    ("Fight Club", "ok so tyler isnt real hes literally the narrators alter ego n he blasts himself thru the cheek 2 get rid of him"),
    ("Interstellar", "the dad falls in2 the black hole n talks 2 his daughter thru the bookcase using a wristwatch lol cant make this up"),
]:
    add(f, D, "slang_typos", t)
# ---------------------------------------------------------------- rhetorical questions
for f, t in [
    ("The Sixth Sense", "Did anyone else notice that the psychologist never once gets a reply from his wife because he is a ghost?"),
    ("Fight Club", "Wasn't it clever that Tyler only ever exists in the narrator's head and the narrator is the one throwing all the punches?"),
    ("Titanic", "Why couldn't they both fit on the floating door? Jack really freezes to death while Rose survives."),
    ("Inception", "So is Cobb still dreaming at the end? Because the spinning top never falls before the cut."),
    ("Parasite", "Anyone else feel sick when the old housekeeper's husband turned out to be hiding in that secret bunker below the kitchen?"),
    ("3 Idiots", "How great was it that Rancho was really the servant's son who borrowed a rich boy's name for his degree?"),
]:
    add(f, D, "question", t)
# ---------------------------------------------------------------- spoiler through reaction / emotion
for f, t in [
    ("Titanic", "I completely lost it when Jack slipped under the black water and Rose let go of his hand."),
    ("The Dark Knight", "My heart broke when Rachel's building went up, and then watching Harvey turn bitter after the fire was brutal."),
    ("Dangal", "I was screaming at the screen when Geeta stood on the podium with the gold medal around her neck while dad watched from a locked room."),
    ("Mad Max: Fury Road", "The moment the young War Boy drove into the tanker and blocked the road gave me chills."),
    ("The Godfather", "Watching the old man collapse among his tomato plants while his grandson played hit me harder than the shootings."),
    ("Interstellar", "I sobbed when the old woman in the hospital bed finally cracked the equation and her dad appeared by Saturn."),
]:
    add(f, D, "emotional_reaction", t)
# ---------------------------------------------------------------- rewatch / hindsight framing
for f, t in [
    ("The Sixth Sense", "Rewatching it, knowing he has been dead since the opening scene, changes every conversation he has with his wife."),
    ("Fight Club", "On a second viewing every scene with Brad Pitt plays differently once you know he is a figment of the lead's mind."),
    ("Parasite", "Second time round the basement dweller's presence under the house adds so much dread to the kitchen scenes."),
    ("Inception", "A rewatch makes the dead wife's role so much clearer; she keeps sabotaging every dream level."),
    ("3 Idiots", "Rewatching with the knowledge that the genius friend borrowed another student's identity made me smile at every classroom scene."),
]:
    add(f, D, "hindsight", t)
# ---------------------------------------------------------------- character fates, no 'ending' words
for f, t in [
    ("The Godfather", "Sonny, the old man and the corrupt police captain are all gone by the time the credits roll."),
    ("Parasite", "Neither the housekeeper nor her husband nor the daughter of the poor family survives the garden party."),
    ("The Dark Knight", "By the final scene the DA is dead, the girlfriend is dead, and the hero is a wanted man."),
    ("Mad Max: Fury Road", "The tyrant and his hulking son are both dead and the warlord's former captive sits on the throne."),
    ("Titanic", "Out of the two lovers only one is still breathing by dawn."),
    ("Fight Club", "He is bleeding from the face, the skyscrapers fall and the woman holds his hand; that is where it stops."),
]:
    add(f, D, "fates", t)
# ---------------------------------------------------------------- sarcastic / negative reviews that spoil
for f, t in [
    ("The Sixth Sense", "Predictable. Anyone who has watched a trailer figures out in ten minutes that the guy is a ghost. Shyamalan thinks we are idiots."),
    ("Fight Club", "Oh wow, shocker, the charismatic anarchist is just the lead's hallucination. Never seen that before. Overrated."),
    ("Inception", "Of course Nolan ends it on a spinning top so everyone can argue on the internet for ten years. Lazy ending."),
    ("Interstellar", "So the Professor knew all along that Plan A was impossible and let everybody burn through their lives? Sloppy writing."),
    ("Titanic", "She could have shared the floating door and saved him but no, the script needed him to die in the water."),
    ("3 Idiots", "Reveal that the supposed hero was only a servant's kid who stole someone's degree is cute but the film glorifies fraud."),
]:
    add(f, D, "sarcastic_negative", t)
# ---------------------------------------------------------------- no names, only roles
for f, t in [
    ("The Sixth Sense", "The child's therapist is the one who is actually dead, which explains why nobody else in the story can see him."),
    ("Parasite", "The rich family's driver and the tutor and the housekeeper are all frauds or hiding something, and the husband in the basement ends up stabbing someone."),
    ("The Dark Knight", "The prosecutor loses half his face and goes on a rampage, so the caped guy has to take the fall for it."),
    ("Interstellar", "The astronaut father dives into the singularity and ends up inside a library of his daughter's bedroom across time."),
    ("Mad Max: Fury Road", "The drifter helps the one-armed driver and her escapees return to the fortress and overthrow the ruler."),
    ("Dangal", "The wrestler father is locked away and the older daughter wins the final using his old lessons."),
]:
    add(f, D, "roles_only", t)
# ---------------------------------------------------------------- one spoiler buried in a long positive review
LONG = ("The direction is confident, the music is moving and the editing keeps the story tight. The supporting cast is excellent and the costume "
        "department deserves an award. The cinematography uses warm colours in the early scenes and cooler ones later. Dialogue is sharp and witty. "
        "The sound design makes even quiet scenes feel tense. I loved the production design and the way each location feels lived in. ")
for f, t in [
    ("Titanic", "Jack dies in the cold water at the end."),
    ("The Sixth Sense", "It turns out the doctor was a ghost all along."),
    ("Fight Club", "Tyler is the narrator's other personality."),
    ("Parasite", "The man hiding in the basement stabs the girl at the party."),
    ("The Dark Knight", "Rachel dies when the building explodes."),
    ("Inception", "The top is still spinning when the screen goes black, so we never learn if he is dreaming."),
]:
    add(f, D, "buried_in_long_review", LONG + t + " Overall a fantastic evening at the cinema.")
# ---------------------------------------------------------------- meta / comparison
for f, t in [
    ("The Sixth Sense", "Has the same twist as every 'the hero was dead all along' story, but with Bruce Willis as a ghost it lands better than most."),
    ("Fight Club", "Same trick as every 'the other guy is in his head' story, but here the narrator literally shoots himself to end it."),
    ("Mad Max: Fury Road", "Reminds me of every revolution story where the escaped slaves seize the palace; the Citadel finale is the best of them."),
    ("Interstellar", "It's 2001 meets a family drama, with the dad communicating through time using gravity and a watch."),
]:
    add(f, D, "comparison", t)

# ================================================================ HARD NEGATIVES: look spoilery, are not
for f, t in [
    ("Titanic", "No spoilers, but the ending is devastating, I cried for an hour. Go in blind."),
    ("The Sixth Sense", "The twist is amazing and you will never see it coming. I will say nothing else, just watch it."),
    ("Fight Club", "Killer soundtrack, dead serious tone and a twisty script that kept me guessing the whole time."),
    ("The Dark Knight", "Heath Ledger's final complete performance is a masterclass. Tragic that he died so young."),
    ("Inception", "The ending sparked ten years of arguments online, which is a testament to how good the film is. No spoilers here."),
    ("Parasite", "A brilliant, shocking thriller that murders your expectations. Dark humour, killer cast."),
    ("The Godfather", "A film about family, power and loyalty. Marlon Brando died in 2004, but his performance is immortal."),
    ("Mad Max: Fury Road", "Dead-on casting, a killer chase and a ton of explosions. I could watch the first hour again."),
    ("Interstellar", "I won't spoil the ending but bring tissues. The black and white contrast of Earth and space is gorgeous."),
    ("Dangal", "A sports drama that actually earns its tears. Aamir Khan's weight transformation is wild."),
    ("3 Idiots", "The twist at the end is cute but I will not say what it is. Hilarious from start to finish."),
    ("Titanic", "A rich girl and a penniless artist fall in love on a doomed ship. The sets are incredible and the romance works."),
    ("Parasite", "A poor family slowly worms its way into a wealthy household by pretending to be qualified. Funny and tense."),
    ("The Dark Knight", "The Joker arrives in Gotham and forces the city into chaos while Batman and the DA try to stop the mob."),
    ("Fight Club", "An insomniac office worker meets a soap salesman and they start an underground fighting club. Chaotic and smart."),
    ("Inception", "A thief who steals secrets from dreams is hired to plant an idea instead. The first hour is pure fun."),
    ("The Sixth Sense", "A child psychologist tries to help a scared little boy who says he sees dead people. Creepy in the best way."),
    ("Interstellar", "With the Earth dying, a farmer-turned-pilot leaves his children to find a new home through a wormhole."),
    ("Mad Max: Fury Road", "A tyrant's escaped wives flee across the desert with a one-armed driver, and a drifter gets pulled into the chase."),
    ("Dangal", "A former wrestler trains his two daughters to become champions in a world that says girls cannot wrestle."),
    ("3 Idiots", "Two friends go looking for the college buddy who vanished after graduation. The campus scenes are brilliant."),
    ("The Godfather", "The ageing head of a crime family is shot early in the film and his youngest son is pulled into the business."),
    ("Titanic", "I died laughing at the dinner table scene and I was dead inside after the music faded. Wow."),
    ("Fight Club", "The first rule is you do not talk about it, so I will not. A killer film."),
    ("Interstellar", "The visuals of the wormhole and the black hole are the best I've seen. The score by Hans Zimmer is huge."),
    ("Inception", "Ellen Page and Joseph Gordon-Levitt are great. The folding Paris street scene is iconic."),
    ("Parasite", "Bong Joon-ho won the Oscars for this and it was deserved. The house design is a character itself."),
    ("The Dark Knight", "I watched it in IMAX, the opening bank heist is unbeatable. Hans Zimmer's two-note theme gives me chills."),
    ("3 Idiots", "Kya movie hai yaar, hasi nahi ruki. Songs bhi mast hain aur college ke scenes ekdum real lage."),
    ("Dangal", "Bahut hi acchi film hai, Aamir ne kamaal kar diya. Poore parivaar ke saath dekhne layak."),
    ("The Godfather", "Slow, patient and gorgeous. Every frame is composed like an oil painting. Highly recommended."),
    ("Mad Max: Fury Road", "lol this movie goes HARD. the guitar guy on the truck is the best thing ever 🔥"),
    ("Titanic", "ok so the first half is cute and the second half is a disaster movie, in the best way. the costumes!!"),
    ("Parasite", "Thrilling start to finish. Don't read anything about it before watching, and don't let anyone spoil it."),
]:
    add(f, C, "hard_clean", t)

out = os.path.join(os.path.dirname(__file__), "gold_adversarial.json")
json.dump({"note": "hand-written, labels not human-verified; see ml/make_adversarial.py", "reviews": R}, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(R), "reviews:", sum(r["kind"] == D for r in R), "disguised spoilers,", sum(r["kind"] == C for r in R), "hard clean")


# ================================================================ SET B: fresh, written AFTER the shield was first measured on set A.
# Used only to check a fix made while looking at set A (so the numbers are not simply 'tuned on the examples').
# Length-matched on purpose: hard-clean reviews are as long as the disguised ones.
B = []


def addb(film, kind, cat, text):
    B.append({"film": film, "kind": kind, "cat": cat, "text": text})


for f, t in [
    ("Titanic", "Honestly the last act wrecked me, because that frozen sea took him and she had to keep going alone."),
    ("The Godfather", "The finale is cold: the youngest gets rid of every rival while his own sister's husband is led away, and his wife is told nothing."),
    ("Inception", "What stays with you is the final shot, where he lets go of the spinning object without waiting to see if it drops."),
    ("Parasite", "The most unsettling part is realising a whole other person has been living below the house the entire time."),
    ("Fight Club", "My favourite twist is that the man he argues with is just him, and the shot through his own cheek is how he wins."),
    ("The Sixth Sense", "The final reveal reframes the whole thing: the man helping the boy was the one who needed help, long past saving."),
    ("The Dark Knight", "That film takes away the hero's love and the city's hero in one night, and the second one ends up as the villain."),
    ("Interstellar", "The father's choice to fall into the dark star is wild, and the way he reaches his kid through the shelf is lovely."),
    ("Mad Max: Fury Road", "That young pale driver crashing the truck on purpose to hold back the pursuers is the best moment of the film."),
    ("Dangal", "The gold medal match, with her teacher-father locked in a side room, is the best sports scene in years."),
    ("3 Idiots", "Learning that the beloved prankster was actually the gardener's boy using a classmate's papers made me cheer."),
    ("Titanic", "She lets the necklace fall into the ocean as an old woman and that is the line that made the whole theatre cry."),
    ("Parasite", "When the quiet man from the cellar finally grabs the knife at the garden party I physically jumped."),
    ("Mad Max: Fury Road", "The mask that holds the ruler's breath gets ripped off, and that is how the chase ends."),
    ("The Godfather", "I did not expect the father to simply sit down among the vegetables and never get up again."),
    ("Inception", "Her husband is long gone and her ghost keeps wrecking the mission, which gives the plot a real heart."),
    ("Interstellar", "The famous scientist knew the big plan could never work and kept it a secret from the crew."),
    ("Fight Club", "Both of them end with their hands joined as the towers crumble behind them, which is the film's final image."),
    ("The Dark Knight", "I never forgave the writers for killing the lawyer's fiancée in that blast; it changes everything after."),
    ("Dangal", "I loved how the older girl wins the title and the old coach in the room is left to just listen to it on the radio."),
]:
    addb(f, D, "paraphrase", t)
for f, t in [
    ("The Sixth Sense", "ngl he was dead the entire movie lol thats why the wife never answers"),
    ("Titanic", "bruh the door!!! he could have fit!!! he freezes!!!! 😭"),
    ("Fight Club", "tyler = hes imagination. bro shoots hisself. building boom. done."),
    ("Parasite", "the dad kills the rich guy at the party n hides below the house forever. 10/10"),
    ("Inception", "the top doesnt fall at the end, its a cliffhanger, he might still be asleep lol"),
    ("The Dark Knight", "2face is born when harvey burns and rachel dies, then bats takes the blame. sad"),
    ("3 Idiots", "Rancho ka asli naam toh kuch aur tha, wo to ek naukar ka beta tha, kya twist tha"),
    ("Mad Max: Fury Road", "joe dies, the mask gets pulled, furiosa rules the citadel. fire movie"),
]:
    addb(f, D, "slang", t)
for f, t in [
    ("Interstellar", "I would have preferred if Murph worked out the secret herself without her father's help from beyond the black hole. Weak science."),
    ("Titanic", "I wanted the artist to live. Sharing the door would have been easy. The writers were cruel for no reason."),
    ("The Sixth Sense", "You spend the whole film with a ghost who thinks he is alive; the film plays fair, I'll give it that."),
    ("Inception", "The wife who keeps killing the team inside the dream is the best part, the ending with the totem is a cheat though."),
    ("Parasite", "The set-piece with the secret bunker beneath the kitchen and the murderous couple is where it stops being a comedy."),
    ("The Godfather", "I hated that the war-hero son lies to his wife after the christening murders. A great character fall."),
]:
    addb(f, D, "opinion_with_reveal", t)
for f, t in [
    ("Fight Club", "Wasn't the soap guy with the red leather jacket in fact the narrator? I swear the film cheats a bit."),
    ("Parasite", "So the old maid really did have a husband hiding down below, and that's why the family had to scramble?"),
    ("Dangal", "Did the dad really have to be shut in a room during the final bout? Gets me every time."),
    ("Mad Max: Fury Road", "Is it true the girls escape just to come back to the place they ran from, and take it over?"),
]:
    addb(f, D, "question", t)
# hard clean, same length range
for f, t in [
    ("Titanic", "The first hour is a gentle love story full of gorgeous sets and warm colours, and the second half is a thrilling disaster picture."),
    ("The Godfather", "Every conversation feels loaded with threat even when everyone speaks softly; the cinematography is dark and beautiful."),
    ("Inception", "The ending will make you want to argue with your friends for hours, which is half the fun. No spoilers, just go and see it."),
    ("Parasite", "A sharp, nasty, funny film about money and class that rewards patience. Don't read anything before you see it."),
    ("Fight Club", "Brad Pitt is magnetic and the narration is razor sharp; the fight scenes are shot with real bite."),
    ("The Sixth Sense", "The performances are fantastic and the final scene is something people will talk about for years. Please avoid spoilers."),
    ("The Dark Knight", "Ledger steals every scene he is in, the heists are tense and the score hums like a siren. A real event film."),
    ("Interstellar", "Gorgeous visuals, a score you can feel in your ribs and a big emotional core about parents and children."),
    ("Mad Max: Fury Road", "A two-hour chase with beautiful stunts, huge machines and almost no dialogue. It's a miracle of practical filmmaking."),
    ("Dangal", "A rousing sports film with real heart; the training sequences are funny and moving at the same time."),
    ("3 Idiots", "Funny, touching and quotable; the friendship at the centre of the story is genuinely warm."),
    ("Titanic", "I wasn't ready for how much I'd care about these characters. The music and the sets are unforgettable."),
    ("Parasite", "The family con in the first act is hilarious, and the way it escalates keeps you in your seat."),
    ("The Dark Knight", "Dark, serious and thrilling. The chase through the city tunnels is one of the best set pieces ever filmed."),
    ("Inception", "Ambitious and fun, with a hallway fight scene that is still impressive years later. The cast is excellent."),
    ("Fight Club", "Angry, stylish and quotable, though some of the humour has not aged well. Still worth the watch."),
    ("The Godfather", "I finally watched it and understand the hype. The wedding scene alone is worth the three hours."),
    ("Mad Max: Fury Road", "Not a single dull minute; the guitar-flamethrower rig alone deserves an award."),
    ("Interstellar", "The film's idea of time and love is moving even when the physics gets heavy. Bring tissues, avoid spoilers."),
    ("Dangal", "Aamir Khan completely vanishes into the father role and the wrestling is intense and believable."),
    ("3 Idiots", "Hostel life, pranks and a very funny professor: a college comedy with a message, all done warmly."),
    ("Titanic", "I died when the string quartet kept playing, it is such a haunting image even for someone who has seen it ten times."),
    ("Fight Club", "dead serious about its themes, killer ending music, a twist you can't see coming: classic. go in blind."),
    ("The Sixth Sense", "creepy, quiet and perfectly acted by the young lead, with a finale that is beyond talked about."),
    ("Parasite", "kya film hai, ekdum gazab. cast bahut mast hai aur direction top class."),
]:
    addb(f, C, "hard_clean", t)

outb = os.path.join(os.path.dirname(__file__), "gold_adversarial_b.json")
json.dump({"note": "set B, written after set A was first measured; see ml/make_adversarial.py", "reviews": B}, open(outb, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("set B:", len(B), "reviews:", sum(r["kind"] == D for r in B), "disguised,", sum(r["kind"] == C for r in B), "hard clean")
