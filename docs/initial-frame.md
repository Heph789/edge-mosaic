- Scrapes updates from edge community and allows people to subscribe to them
- The actual website will be like a mosaic and have a tile for each participant

# MVP

**Feeder: User who connects their content platforms**

- Signs up using their edgeos email
    - Verifies – I should ask if there’s a way to check if an email is a valid edge email. For now just csv
- Puts in content links:
    - Substack
    - X
    - Personal blog/website (potentially harder)
    - Bluesky (low priority)

**Subscriber/viewer**

- Signs up using edgeos email
- Can choose subscription preferences
    - Frequency (weekly - monthly)
- Can search people by name
    - Later: by interest/category
- Can subscribe to people
- Gets an email every month (or whatever their frequency is with their digest)

**Digest email**

- This digest is basically a summary of updates from the people the user has subscribed to
- It should:
    - Filter out insignificant updates (like unimportant tweets)
    - Be organized by “Feeder”
        - “From John…. From Mike…. From Laurent…”
    - Give “headlines” or titles if available
    - Somehow filter if there’s too many updates, either by a random filter or by letting the user select their priority per user
- It should not:
    - Give AI summaries of content. For the user to get the value of the content they must click into it

**Additional Notes:**

- No need to worry about the mosaic design for the mvp, just focus on the actual functionality