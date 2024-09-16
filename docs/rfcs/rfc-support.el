;; Function to update RFC status and last updated date
(defun update-rfc-metadata ()
  "Update the RFC status and last updated date based on the current TODO state."
  (interactive)
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* \\(DRAFT\\|SUBMITTED\\|REVIEW\\|REVISE\\|APPROVED\\|REJECTED\\|DEFERRED\\|WITHDRAWN\\|IMPLEMENTING\\|IMPLEMENTED\\|OBSOLETE\\) Metadata" nil t)
      (let ((new-status (match-string 1)))
        ;; Update Status field
        (re-search-forward "^- Status: .*$" nil t)
        (replace-match (format "- Status: %s" new-status))
        ;; Update Last Updated field
        (re-search-forward "^- Last Updated: .*$" nil t)
        (replace-match (format "- Last Updated: [%s]"
                               (format-time-string "%Y-%m-%d %a")))))))

;; Add hook to org-after-todo-state-change-hook
(add-hook 'org-after-todo-state-change-hook 'update-rfc-metadata)

;; Custom TODO keyword faces for RFC states
(setq org-todo-keywords
      '((sequence
         "DRAFT(d)" "SUBMITTED(s)" "REVIEW(r)" "REVISE(v)"
         "APPROVED(a)" "REJECTED(x)" "DEFERRED(f)" "WITHDRAWN(w)"
         "IMPLEMENTING(i)" "IMPLEMENTED(m)" "|" "OBSOLETE(o)")))

(setq org-todo-keyword-faces
      '(("DRAFT" . (:foreground "gold" :weight bold))
        ("SUBMITTED" . (:foreground "orange" :weight bold))
        ("REVIEW" . (:foreground "deep sky blue" :weight bold))
        ("REVISE" . (:foreground "tomato" :weight bold))
        ("APPROVED" . (:foreground "lime green" :weight bold))
        ("REJECTED" . (:foreground "red" :weight bold))
        ("DEFERRED" . (:foreground "dark orchid" :weight bold))
        ("WITHDRAWN" . (:foreground "gray" :weight bold))
        ("IMPLEMENTING" . (:foreground "chocolate" :weight bold))
        ("IMPLEMENTED" . (:foreground "forest green" :weight bold))
        ("OBSOLETE" . (:foreground "dim gray" :weight bold))))

(defun display-rfc-state-description ()
  "Display the long-form description of the current RFC state."
  (interactive)
  (let* ((state (org-get-todo-state))
         (descriptions
          '(("DRAFT" . "Work in Progress: Initial creation and refinement")
            ("SUBMITTED" . "Awaiting Review: Formally submitted for consideration")
            ("REVIEW" . "Under Scrutiny: Active community and stakeholder review")
            ("REVISE" . "Feedback Integration: Undergoing revisions based on input")
            ("APPROVED" . "Green Light: Accepted and ready for implementation")
            ("REJECTED" . "Not Proceeding: Declined for implementation")
            ("DEFERRED" . "On Hold: Postponed for future consideration")
            ("WITHDRAWN" . "Retracted: Removed from consideration by author(s)")
            ("IMPLEMENTING" . "In Progress: Actively being implemented")
            ("IMPLEMENTED" . "Mission Accomplished: Implementation is complete")
            ("OBSOLETE" . "Archived: No longer relevant or superseded")))
         (description (cdr (assoc state descriptions))))
    (if description
        (message "RFC State: %s - %s" state description)
      (message "Unknown RFC state: %s" state))))

;; Local Variables:
;; eval: (org-babel-tangle)
;; org-babel-tangle-file: "rfc-support.el"
;; End:
