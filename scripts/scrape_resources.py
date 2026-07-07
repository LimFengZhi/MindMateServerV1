"""Upload the in-app self-help guides & exercises to the Supabase `resources`
table.

    python scripts/scrape_resources.py            # REPLACE all resource rows
    python scripts/scrape_resources.py --dry-run  # preview without uploading

Unlike the earlier version of this script (which linked out to external
sites), the content below is written INTO the app — users read the guide or
follow the exercise without leaving MindMate, Intellect-style. Every item is
based on a resource linked from the TAR UMT Student Counselling Service
self-help page; that source appears as a reference hyperlink at the bottom of
the detail view (`external_url` + `source`).

Each resource is kind='article': the `info` text fills the first tab and
`steps` fill the second ("How to do it" for exercises, "Steps to overcome it"
for guides).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root

# Windows consoles default to cp1252; never let logging kill the upload.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Every resource: slug, title, category, summary (card text), source +
# reference (the hyperlink shown under the content), info (first tab), and
# steps [(title, content)] (second tab). Order here = display order.
RESOURCES = [
    # ================= Calm Down Exercises =================
    dict(
        slug="stopp-technique",
        title="STOPP Technique",
        category="Calm Down Exercises",
        summary="A one-minute skill for the moment between a trigger and your reaction.",
        source="Therapy in a Nutshell (YouTube)",
        reference="https://www.youtube.com/watch?v=3NHZkQ57wzE",
        info=(
            "STOPP is a quick skill from cognitive behavioural therapy (CBT). It works "
            "in the small space between something upsetting happening and how you react "
            "to it — a sharp message, a bad grade, a spiralling thought.\n\n"
            "Instead of reacting on autopilot, STOPP walks you through five tiny moves "
            "that put you back in charge. It takes less than a minute, and nobody around "
            "you will even notice you're doing it."
        ),
        steps=[
            ("S — Stop", "Pause whatever you're doing. Just stopping for a moment breaks "
             "the automatic reaction before it takes over."),
            ("T — Take a breath", "Take one slow, deliberate breath. A longer exhale tells "
             "your body the emergency is off."),
            ("O — Observe", "Notice what's happening inside you: What am I thinking? What am "
             "I feeling? Where do I feel it in my body? Name it without judging it."),
            ("P — Pull back", "Zoom out for perspective. Is this thought a fact or an "
             "opinion? What would I say to a friend in this situation? Will this matter in "
             "six months?"),
            ("P — Proceed", "Continue with something that actually helps. Act on your "
             "values, not the surge of the moment — do what works."),
        ],
    ),
    dict(
        slug="478-breathing",
        title="4-7-8 Breathing Exercise",
        category="Calm Down Exercises",
        summary="Breathe in for 4, hold for 7, out for 8 — a natural calmer for body and mind.",
        source="YouTube",
        reference="https://www.youtube.com/watch?v=p8fjYPC-k2k",
        info=(
            "4-7-8 breathing is a slow breathing pattern popularised by Dr Andrew Weil, "
            "based on ancient yogic breathing. The long, slow exhale activates your "
            "body's rest-and-digest response, easing a racing heart and busy mind.\n\n"
            "Use it before sleep, before a presentation or exam, or any time anxiety "
            "starts to build. It gets stronger with practice — try it twice a day."
        ),
        steps=[
            ("Get comfortable", "Sit with your back supported, or lie down. Rest the tip of "
             "your tongue behind your upper front teeth and exhale fully through your mouth."),
            ("Breathe in — 4", "Close your mouth and breathe in quietly through your nose "
             "for a count of 4."),
            ("Hold — 7", "Hold your breath gently for a count of 7. If 7 feels too long at "
             "first, use a shorter hold and build up."),
            ("Breathe out — 8", "Exhale slowly and completely through your mouth for a count "
             "of 8, with a soft whoosh sound."),
            ("Repeat 4 rounds", "Do up to four rounds. Feeling slightly light-headed at "
             "first is common — if it's uncomfortable, pause and breathe normally."),
        ],
    ),
    dict(
        slug="54321-grounding",
        title="5-4-3-2-1 Grounding Exercise",
        category="Calm Down Exercises",
        summary="Use your five senses to step out of anxious thoughts and back into the present.",
        source="YouTube",
        reference="https://www.youtube.com/watch?v=30VMIEmA114",
        info=(
            "When anxiety or panic spikes, your mind gets pulled into worries about the "
            "past or future. Grounding brings you back to right now, using the one thing "
            "that is always in the present: your senses.\n\n"
            "The 5-4-3-2-1 exercise walks down your five senses one by one. Go slowly — "
            "the point isn't to finish the list, it's to really notice each thing."
        ),
        steps=[
            ("Start with one breath", "Take a slow, deep breath. Let your shoulders drop."),
            ("5 things you can SEE", "Look around and name five things you can see. Notice "
             "small details — colours, shapes, light."),
            ("4 things you can TOUCH", "Notice four things you can feel: your feet on the "
             "floor, your clothes, the chair, the air on your skin."),
            ("3 things you can HEAR", "Listen for three sounds — near or far. Traffic, a "
             "fan, your own breathing."),
            ("2 things you can SMELL", "Notice two smells, or move to something you can "
             "smell — your drink, your sleeve, fresh air."),
            ("1 thing you can TASTE", "Notice one taste in your mouth, or take a sip of "
             "something. Then finish with another slow breath."),
        ],
    ),
    dict(
        slug="deep-breathing",
        title="Deep Breathing Exercise",
        category="Calm Down Exercises",
        summary="Slow belly breathing that switches your body from alarm mode to calm.",
        source="YouTube",
        reference="https://www.youtube.com/watch?v=odADwWzHR24",
        info=(
            "When you're stressed, breathing turns fast and shallow, which keeps your "
            "body's alarm system switched on. Deep (diaphragmatic) breathing does the "
            "opposite: slow breaths into your belly signal your nervous system that "
            "you're safe.\n\n"
            "A few minutes is enough to lower tension in the moment, and practising "
            "daily makes it work faster when you really need it."
        ),
        steps=[
            ("Settle in", "Sit comfortably or lie down. Put one hand on your chest and one "
             "on your belly."),
            ("Breathe into your belly", "Inhale slowly through your nose for about 4 counts. "
             "The hand on your belly should rise; the one on your chest stays almost still."),
            ("Exhale slowly", "Breathe out gently through pursed lips for about 6 counts, "
             "letting your belly fall. The longer exhale is what calms you."),
            ("Keep a steady rhythm", "Continue for 5–10 slow rounds. If your mind wanders, "
             "just bring it back to the feeling of your hands moving."),
            ("Practise daily", "Do a few minutes every day — not only in a crisis — so calm "
             "breathing becomes your body's default."),
        ],
    ),

    # ================= Stress =================
    dict(
        slug="understanding-stress",
        title="Understanding Stress",
        category="Stress",
        summary="What stress is, how to recognise your signs, and how to ease the pressure.",
        source="Mind UK",
        reference="https://www.mind.org.uk/information-support/types-of-mental-health-problems/stress/signs-and-symptoms-of-stress/",
        info=(
            "Stress is how your body and mind respond when the pressure on you feels "
            "bigger than your resources. In small doses it can sharpen focus, but when "
            "it goes on and on it drains energy and affects sleep, mood and health.\n\n"
            "Stress shows up differently for everyone — in your feelings (irritable, "
            "overwhelmed, anxious), your body (headaches, tight muscles, tiredness, "
            "changed appetite) and your behaviour (snapping at people, avoiding things, "
            "trouble concentrating). Knowing your own signs is the first step to "
            "managing it."
        ),
        steps=[
            ("Know your signs", "Notice your personal early warnings — racing thoughts, "
             "shallow breathing, poor sleep, skipped meals, pulling away from friends."),
            ("Find the source", "Write down what's pressuring you right now. Naming it "
             "makes it feel more manageable than a vague cloud of stress."),
            ("Sort what you control", "Split the list into 'can change' and 'can't change'. "
             "Put your energy into the first list, and practise letting go of the second."),
            ("Build in recovery", "Schedule small breaks, movement and a steady bedtime. "
             "Stress builds up when there's no space to come back down."),
            ("Calm your body", "Use one of the Calm Down Exercises here — deep breathing or "
             "grounding — when you feel the pressure rising."),
            ("Talk about it", "Share how you're doing with someone you trust, or reach out "
             "to the campus counselling service. You don't have to manage it alone."),
        ],
    ),
    dict(
        slug="exam-stress-tips",
        title="5 Tips to Deal with Exam Stress",
        category="Stress",
        summary="Five self-soothing tips — one for each sense — to stay steady through exam season.",
        source="DialecticalBehaviorTherapy.com",
        reference="https://dialecticalbehaviortherapy.com/distress-tolerance/self-soothing/",
        info=(
            "Exam season stacks pressure day after day, and pushing harder without "
            "relief usually backfires. Self-soothing is a distress-tolerance skill from "
            "dialectical behaviour therapy (DBT): you calm your nervous system by giving "
            "each of your five senses something comforting.\n\n"
            "Pick one tip per study break. A few minutes is enough — the goal is to "
            "come back to your notes steadier, not to escape them."
        ),
        steps=[
            ("1. Soothe your eyes", "Step away from the screen. Look out a window, walk "
             "somewhere green, or keep a folder of pictures you love and browse it slowly."),
            ("2. Soothe your ears", "Between study sessions, play calming or instrumental "
             "music, nature sounds, or a voice that relaxes you."),
            ("3. Soothe your nose", "Light a scented candle, make a fragrant drink, or step "
             "outside for fresh air. Familiar, pleasant smells settle the body quickly."),
            ("4. Soothe your taste", "Slowly enjoy a warm drink or a small favourite snack. "
             "Taste it properly instead of eating on autopilot over your notes."),
            ("5. Soothe your touch", "Take a warm shower, wrap up in a soft blanket, stretch, "
             "or hold something comforting. Then return to studying — calmer and clearer."),
        ],
    ),

    # ================= Anger =================
    dict(
        slug="understanding-anger",
        title="Understanding Anger",
        category="Anger",
        summary="Anger is a normal emotion — the skill is understanding what it's telling you.",
        source="HelpGuide.org",
        reference="https://www.helpguide.org/articles/relationships-communication/anger-management.htm",
        info=(
            "Anger is a completely normal, healthy emotion — a signal that something "
            "feels wrong, unfair or threatening. It only becomes a problem when it "
            "explodes out of control and starts hurting you, your studies or your "
            "relationships.\n\n"
            "Managing anger doesn't mean never feeling it or bottling it up. It means "
            "understanding the message behind the anger and learning to express it in a "
            "way that makes things better instead of worse."
        ),
        steps=[
            ("Spot your warning signs", "Anger shows in the body first: clenched jaw or "
             "fists, heat in the face, a knot in your stomach, a louder voice. Catch it early."),
            ("Look underneath", "Anger often covers another feeling — hurt, embarrassment, "
             "stress or feeling disrespected. Ask yourself what's really going on."),
            ("Know your triggers", "Notice the patterns: certain situations, times (tired, "
             "hungry, deadline week) or people that light the fuse. Plan for them."),
            ("Cool down first", "Before responding, give the surge time to pass — use the "
             "STOPP technique or a slow breathing exercise from this page."),
            ("Express it assertively", "Once calm, say what you need without attacking: "
             "'I feel… when… because…'. Assertive isn't aggressive — it's honest and fair."),
        ],
    ),
    dict(
        slug="anger-management-tips",
        title="Anger Management Tips",
        category="Anger",
        summary="Quick, practical ways to cool down in the heat of the moment.",
        source="Verywell Mind",
        reference="https://www.verywellmind.com/anger-management-strategies-4178870",
        info=(
            "When your temper is already rising, long-term insight doesn't help much — "
            "you need something that works in the next sixty seconds.\n\n"
            "These quick strategies lower the heat of the moment so you can respond as "
            "the person you want to be. Try them all and keep the two or three that work "
            "best for you."
        ),
        steps=[
            ("Count before you speak", "Count down slowly from 10 (or 100 when it's bad). "
             "The delay lets the first, hottest wave of anger pass."),
            ("Take a breather", "Breathe slowly and deeply — long exhales — or step out of "
             "the room for a few minutes. Distance is not defeat."),
            ("Move your body", "Anger is energy. Walk fast, climb stairs, do a few push-ups "
             "— burn the charge off physically."),
            ("Change the channel", "Shift your attention: change your environment, wash "
             "your face, put on music. Rumination feeds anger; interruption starves it."),
            ("Relax your muscles", "Scan for tension — jaw, shoulders, fists — and "
             "deliberately loosen each spot. A relaxed body cools a hot mind."),
            ("Use a calming phrase", "Repeat something short to yourself: 'Relax. This will "
             "pass. I can handle this calmly.'"),
        ],
    ),

    # ================= Relationships =================
    dict(
        slug="breakup-coping",
        title="Dealing with a Breakup or Divorce",
        category="Relationships",
        summary="Grieving the end of a relationship is real grief — here's how to heal through it.",
        source="HelpGuide.org",
        reference="https://www.helpguide.org/articles/grief/dealing-with-a-breakup-or-divorce.htm",
        info=(
            "The end of a relationship is a real loss, and what follows is real grief — "
            "sadness, anger, relief and confusion can all show up, sometimes in the same "
            "hour. That's normal, and it doesn't mean something is wrong with you.\n\n"
            "Healing isn't a straight line and it can't be rushed. What helps most is "
            "letting yourself grieve, leaning on people who care about you, and taking "
            "care of the basics while your heart catches up."
        ),
        steps=[
            ("Let yourself grieve", "Don't fight the feelings or judge them. Trying to "
             "suppress grief usually makes it last longer — let it move through you."),
            ("Don't go through it alone", "Spend time with friends and family, even when "
             "you don't feel like it. Talking about it out loud genuinely lightens it."),
            ("Keep the basics going", "Sleep, regular meals, movement, showers, class. "
             "Routine is quiet medicine when everything else feels shaken."),
            ("Pause big decisions", "Give yourself time before making major choices about "
             "courses, moves or new relationships. Grieving minds decide differently."),
            ("Cope in ways that heal", "Be careful with numbing — alcohol, endless "
             "scrolling, comfort-eating. They postpone the pain instead of easing it."),
            ("Rediscover yourself", "Reconnect with interests, people and plans that are "
             "yours. This chapter ending makes room for the next one."),
        ],
    ),
]


def build_rows():
    """Rows for the `resources` table, plus per-slug steps."""
    rows, steps_by_slug = [], {}
    for order, item in enumerate(RESOURCES):
        rows.append({
            "slug": item["slug"],
            "title": item["title"],
            "category": item["category"],
            "kind": "article",              # content lives in the app
            "summary": item["summary"],
            "info": item["info"],
            "external_url": item["reference"],  # shown as the reference link
            "source": item["source"],
            "image_url": None,
            "sort_order": order,
            "is_published": True,
        })
        steps_by_slug[item["slug"]] = item["steps"]
    return rows, steps_by_slug


def upload(rows, steps_by_slug):
    from app.extensions import get_sb
    sb = get_sb()

    # Probe for the new columns BEFORE deleting anything, so a missing
    # migration can't leave the table empty.
    try:
        sb.table("resources").select("kind, external_url, source").limit(1).execute()
    except Exception as e:
        sys.exit(
            "The resources table is missing the new columns "
            f"(kind / external_url / source): {e}\n"
            "Run the 'Additive (idempotent)' resources block in schema.sql "
            "via the Supabase SQL editor, then re-run this script."
        )

    # Full replace: the table's contents are owned by this script.
    # (resource_steps rows go with them via ON DELETE CASCADE.)
    sb.table("resources").delete().neq("slug", "").execute()

    for row in rows:
        inserted = sb.table("resources").insert(row).execute()
        resource_id = inserted.data[0]["id"]
        steps = [{
            "resource_id": resource_id,
            "step_order": j,
            "title": title,
            "content": content,
        } for j, (title, content) in enumerate(steps_by_slug[row["slug"]])]
        if steps:
            sb.table("resource_steps").insert(steps).execute()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the content without touching the database")
    args = parser.parse_args()

    rows, steps_by_slug = build_rows()

    if args.dry_run:
        current = None
        for row in rows:
            if row["category"] != current:
                current = row["category"]
                print(f"\n=== {current} ===")
            print(f"  {row['title']}  ({len(steps_by_slug[row['slug']])} steps, "
                  f"ref: {row['source']})")
        print(f"\n[dry-run] {len(rows)} resources ready; database untouched.")
        return

    upload(rows, steps_by_slug)
    total_steps = sum(len(s) for s in steps_by_slug.values())
    print(f"[upload] replaced resources table with {len(rows)} guides/exercises "
          f"({total_steps} steps).")


if __name__ == "__main__":
    main()
