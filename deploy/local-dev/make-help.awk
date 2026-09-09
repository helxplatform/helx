# Build `make help` output from the Makefile itself, so that a target and its
# documentation cannot drift apart.
#
# A target is documented by a run of comment lines directly above it, with a
# blank line separating that run from whatever came before:
#
#     # docker-build SERVICE=<name>: Build one service image as CI builds it
#     # Every following comment line continues the description.
#     docker-build:
#
# The first line must name the target it documents. That requirement is what
# keeps internal notes out of the help: a comment block that does not open with
# "<target>:" is written for whoever reads the Makefile, not for whoever runs
# it, and is ignored. Anything between the target name and the colon is usage
# -- SERVICE=<name> above -- and is shown with the target.
#
# Sections come from two markers:
#
#     ##@ <topic> <Section title>    put what follows in <topic>, under <title>
#     ##> <text>                     emit <text> verbatim, where it appears
#
# Sections are buffered and printed in the order their titles first appear, so
# a title may be reopened as many times as it takes. Targets group by the marker
# above them, never by where they sit in the file, and nothing has to be moved
# to read well.
#
# Pass -v topic=<name> to print one topic, or nothing to print them all:
#
#     awk -f deploy/local-dev/make-help.awk -v topic=ci Makefile

function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }

function add_row(title, label, description, padded,   i) {
    i = ++rows[title]
    row_label[title, i] = label
    row_text[title, i] = description
    row_padded[title, i] = padded
}

/^##@/ {
    line = trim(substr($0, 4))
    section_topic = line
    sub(/[ \t].*$/, "", section_topic)
    current = trim(substr(line, length(section_topic) + 1))
    if (!(current in seen)) {
        seen[current] = 1
        order[++sections] = current
        topic_of[current] = section_topic
    }
    documented = 0
    armed = 1
    next
}

/^##>/ {
    # Verbatim really is verbatim: a literal line keeps its own indentation,
    # which is what lets one line up its own columns.
    literal = substr($0, 4)
    if (substr(literal, 1, 1) == " ") literal = substr(literal, 2)
    if (current != "") add_row(current, "", "  " literal, 0)
    documented = 0
    armed = 1
    next
}

/^[ \t]*$/ { armed = 1; documented = 0; next }

/^#/ {
    if (armed || documented) doc[documented++] = trim(substr($0, 2))
    next
}

{
    if (documented > 0 && current != "" && match($0, /^[A-Za-z0-9_-]+:([^=]|$)/)) {
        name = substr($0, 1, index($0, ":") - 1)
        # The block documents this target only if it opens by naming it.
        if (index(doc[0], name) == 1 && index(doc[0], ": ") > 0) {
            usage = substr(doc[0], 1, index(doc[0], ": ") - 1)
            if (usage == name || index(usage, name " ") == 1) {
                add_row(current, "  make " usage, substr(doc[0], index(doc[0], ": ") + 2), 1)
                for (i = 1; i < documented; i++) add_row(current, "", doc[i], 1)
            }
        }
    }
    armed = 0
    documented = 0
}

END {
    # One column width across everything being printed, so sections line up
    # with each other rather than each finding its own margin.
    for (s = 1; s <= sections; s++) {
        title = order[s]
        if (topic != "" && topic != topic_of[title]) continue
        for (i = 1; i <= rows[title]; i++)
            if (row_padded[title, i] && length(row_label[title, i]) + 2 > width)
                width = length(row_label[title, i]) + 2
    }
    # A computed format string rather than %-*s, which BWK awk does not accept.
    format = "%-" width "s"

    for (s = 1; s <= sections; s++) {
        title = order[s]
        if (topic != "" && topic != topic_of[title]) continue
        if (printed++) print ""
        print title ":"
        for (i = 1; i <= rows[title]; i++) {
            if (row_padded[title, i])
                print sprintf(format, row_label[title, i]) row_text[title, i]
            else
                print row_text[title, i]
        }
    }
}
