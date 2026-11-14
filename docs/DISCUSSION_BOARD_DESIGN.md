# Discussion board design and feature inventory

The board is a course-scoped workspace reached by the icon at the end of the **Course units** heading. Course home has no permanent navigation rail. The Q&A screen follows the supplied reference: folder bar, searchable feed, and selected post detail. It uses Trellis branding.

## Piazza-style feature inventory

| Capability | Current state | Teacher control |
| --- | --- | --- |
| Questions, notes, polls | Implemented | Allow student posts, notes, and polls separately |
| Public and instructor-only posts | Implemented | Allow private student posts |
| Anonymous posts and followups | Implemented; classmates-only and everyone modes | Allow anonymity and anonymity from staff separately |
| Folders and folder navigation | Implemented; teachers create, rename, reorder, and remove | Require a folder when posting |
| Search, sorting, and filters | Implemented; unread, unresolved, following, bookmarked, reading list, own posts, instructor posts, archive | None |
| Pinned posts and reading list | Implemented | Staff curate; reading list can be disabled |
| Required reading before posting | Implemented; the composer shows unread and required counts | Staff mark public posts required and enable the posting gate |
| Saved drafts | Implemented on the server, one per course member | None |
| Composer editor modes and preview | Formatted Markdown toolbar, literal plain text, Markdown, and preview | None |
| Themed dropdown menus | Implemented in the board and across the course, gradebook, settings, and review screens | None |
| Shared student and instructor answers | Implemented | Allow student answer edits; staff endorse student answer |
| Followup threads, comments, resolution, likes | Implemented | Staff can resolve and remove any followup |
| Post likes, bookmark, follow, archive, mark unread, views, direct link | Implemented | Staff can lock, endorse, and remove posts |
| Post revisions and history | Implemented | Staff can hide public history |
| Attachments | Implemented for existing posts; private course-scoped downloads, 2 MB limit | Staff can remove attachments |
| Participation statistics and CSV | Implemented | Staff only; students see their own activity |
| Poll voting and result counts | Implemented | Staff can disable student polls |
| Code display | Implemented with fenced code blocks | None |
| Email or push notifications, digest preferences, mentions | Not implemented | Would require notification preferences and delivery infrastructure |
| Live Q&A and chat | Not implemented | Would require live session scheduling and realtime delivery |
| Duplicate question suggestions and merges | Not implemented | Would require similarity search and merge moderation |
| Fully visual rich editor, inline images, equations, and collaborative answer revision history | Not implemented | Would require an editor and richer document model |
| Subfolders, bulk moderation, and granular analytics | Not implemented | Would require additional organization and reporting tools |

These are Piazza-style capabilities, not a claim of full Piazza product parity. Piazza's own guides describe [student feeds](https://support.piazza.com/support/solutions/articles/48000616734-students-a-guide-to-your-feed), [instructor and student roles](https://support.piazza.com/support/solutions/articles/48000616672-instructor-accounts-vs-student-accounts), [folders](https://support.piazza.com/support/solutions/articles/48001080726-instructors-create-custom-folders), [class configuration](https://support.piazza.com/support/solutions/articles/48001141422-configure-your-class), and [statistics](https://support.piazza.com/support/solutions/articles/48000616670-instructors-class-statistics).

## Teacher and student views

Students see **Q&A**, **Resources**, and **My activity**. They can create permitted post types, ask privately when enabled, use anonymity when enabled, contribute to the shared student answer, follow discussions, and vote in polls. Private posts are visible only to their author and course staff. Their feed and search exclude other students' private posts.

Teachers see **Q&A**, **Resources**, **Statistics**, and **Manage board**. Manage board contains the class-wide posting, anonymity, folder, and reading-list settings, including whether required reading blocks new posts. Post-specific controls remain beside the post: pin, add to reading list, mark required reading, lock, endorse, hide history, and remove. Teachers can see a real name for classmates-only anonymous posts, but not for posts anonymous to everyone. In student-preview mode, the board uses student permissions and hides staff tools.

The **Resources** tab shows notes from the same board. The shared answer areas belong to questions; followups are separate conversations under a post. Staff can mark a followup resolved independently of whether the main question has an answer.
