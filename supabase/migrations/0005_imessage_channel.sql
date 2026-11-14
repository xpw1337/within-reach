-- Photon 2.0 iMessage as a responder channel (approved by the team lead on 2026-11-14).
-- A dispatch row uses 'imessage' when the responder was reached by iMessage only
-- (no call placed). Replies map back to the responder's open dispatch.
alter type dispatch_channel add value if not exists 'imessage';
