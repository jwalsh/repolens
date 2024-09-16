(require 'org)

(defun repolens-get-rfc-metadata ()
  "Extract RFC metadata from the current buffer."
  (save-excursion
    (goto-char (point-min))
    (let ((case-fold-search t)
          metadata)
      (setq metadata
            (list :filename (repolens-get-rfc-filename)
                  :title (org-get-title)
                  :id (progn
                        (when (re-search-forward "^\\* \\(DRAFT \\)?Metadata$" nil t)
                          (org-entry-get nil "ID")))
                  :rfc-number (when (re-search-forward ":RFC_NUMBER:\\s-*\\(.*\\)" nil t)
                                (match-string 1))
                  :status (when (re-search-forward ":STATUS:\\s-*\\(.*\\)" nil t)
                            (match-string 1))
                  :author (when (re-search-forward ":AUTHOR:\\s-*\\(.*\\)" nil t)
                            (match-string 1))
                  :created (when (re-search-forward ":CREATED:\\s-*\\(.*\\)" nil t)
                             (match-string 1))
                  :last-updated (when (re-search-forward ":LAST_UPDATED:\\s-*\\(.*\\)" nil t)
                                  (match-string 1))
                  :github-issue (when (re-search-forward ":GITHUB_ISSUE:\\s-*\\(.*\\)" nil t)
                                  (match-string 1))))
      
      ;; If RFC number is not found in properties, try to extract from title or filename
      (unless (plist-get metadata :rfc-number)
        (setq metadata 
              (plist-put metadata :rfc-number
                         (or (when (string-match "RFC \\([0-9]+\\)" (plist-get metadata :title))
                               (match-string 1 (plist-get metadata :title)))
                             (when (string-match "^\\([0-9]+\\)-" (plist-get metadata :filename))
                               (match-string 1 (plist-get metadata :filename)))))))
      
      ;; Ensure we have an ID
      (unless (plist-get metadata :id)
        (repolens-ensure-rfc-metadata-id)
        (setq metadata (plist-put metadata :id (org-id-get-create))))
      
      metadata)))

;; Update the repolens-update-rfc-metadata function to use the new metadata extraction
(defun repolens-update-rfc-metadata ()
  "Update the RFC metadata, including last updated date and status."
  (interactive)
  (let* ((metadata (repolens-get-rfc-metadata))
         (current-todo-state (org-get-todo-state)))
    (when (plist-get metadata :filename)
      (save-excursion
        ;; Update property drawer
        (goto-char (point-min))
        (when (re-search-forward "^\\* \\(DRAFT \\)?Metadata$" nil t)
          (let ((metadata-id (plist-get metadata :id)))
            (when metadata-id
              (org-entry-put nil "LAST_UPDATED" (format-time-string "[%Y-%m-%d %a]"))
              (org-entry-put nil "RFC_NUMBER" (plist-get metadata :rfc-number))
              (when current-todo-state
                (org-entry-put nil "STATUS" current-todo-state)))))
        
        ;; Update list item
        (goto-char (point-min))
        (when (re-search-forward "^- Status:" nil t)
          (kill-line)
          (insert (format " %s" (or current-todo-state "DRAFT"))))
        
        ;; Update Last Updated in list item
        (goto-char (point-min))
        (when (re-search-forward "^- Last Updated:" nil t)
          (kill-line)
          (insert (format " %s" (format-time-string "[%Y-%m-%d %a]"))))))))

(defun repolens-on-todo-state-change ()
  "Function to be called when the TODO state changes."
  (when (string-match "^[0-9]+-.*\\.org$" (buffer-name))
    (repolens-update-rfc-metadata)))

(add-hook 'org-after-todo-state-change-hook 'repolens-on-todo-state-change)

(provide 'repolens-rfc-metadata)

(defun repolens-get-rfc-filename ()
  "Get the RFC filename from the buffer name or file name."
  (or (and buffer-file-name
           (string-match "/docs/rfcs/\\([0-9]+-.*\\.org\\)$" buffer-file-name)
           (match-string 1 buffer-file-name))
      (and (buffer-name)
           (string-match "^\\([0-9]+-.*\\.org\\)$" (buffer-name))
           (match-string 1 (buffer-name)))))

(defun repolens-ensure-rfc-metadata-id ()
  "Ensure that the RFC metadata section has an ID property."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* \\(DRAFT \\)?Metadata$" nil t)
      (unless (org-entry-get nil "ID")
        (org-id-get-create)))))

(defun repolens-update-rfc-metadata ()
  "Update the RFC metadata, including last updated date."
  (interactive)
  (let ((filename (repolens-get-rfc-filename)))
    (when filename
      (save-excursion
        (goto-char (point-min))
        (when (re-search-forward "^\\* \\(DRAFT \\)?Metadata$" nil t)
          (let ((metadata-id (org-entry-get nil "ID")))
            (when metadata-id
              (org-entry-put nil "LAST_UPDATED" (format-time-string "[%Y-%m-%d %a]")))))))))

(defun repolens-initialize-rfc ()
  "Initialize or update RFC metadata."
  (when (repolens-get-rfc-filename)
    (repolens-ensure-rfc-metadata-id)
    (repolens-update-rfc-metadata)))

(defun repolens-update-rfc-last-updated ()
  "Update the Last Updated field in the RFC metadata."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* \\(DRAFT \\)?Metadata$" nil t)
      (org-entry-put nil "LAST_UPDATED" (format-time-string "[%Y-%m-%d %a]")))))

(add-hook 'find-file-hook 'repolens-initialize-rfc)
(add-hook 'before-save-hook 'repolens-update-rfc-metadata)
(add-hook 'before-save-hook 'repolens-update-rfc-last-updated)

(require 'projectile)

(defun repolens-create-new-rfc ()
  "Create a new RFC file with the next available number."
  (interactive)
  (let* ((rfc-dir (expand-file-name "docs/rfcs" (projectile-project-root)))
         (next-number (1+ (apply #'max (mapcar (lambda (name)
                                                 (string-to-number (substring name 0 3)))
                                               (directory-files rfc-dir nil "^[0-9]+-.*\\.org$")))))
         (file-name (format "%03d-repolens-new-rfc.org" next-number)))
    (find-file (expand-file-name file-name rfc-dir))
    (insert (format "#+TITLE: RFC %03d: New RFC Title\n\n* DRAFT Metadata\n:PROPERTIES:\n:ID:       %s\n:RFC_NUMBER: %03d\n:TITLE:     New RFC Title\n:AUTHOR:    Your Name\n:STATUS:    DRAFT\n:CREATED:   %s\n:LAST_UPDATED: %s\n:END:\n\n* Abstract\n\n* Motivation\n\n* Proposal\n\n* Drawbacks\n\n* Alternatives\n\n* Implementation Plan\n\n* Open Questions\n"
                    next-number
                    (org-id-new)
                    next-number
                    (format-time-string "[%Y-%m-%d %a]")
                    (format-time-string "[%Y-%m-%d %a]")))
    (save-buffer)))

(defun repolens-run-tests ()
  "Run RepoLens tests using pytest."
  (interactive)
  (projectile-run-command-in-root "pytest"))

(defun repolens-run-main ()
  "Run the main.py script of RepoLens."
  (interactive)
  (projectile-run-command-in-root "python main.py"))

(define-key projectile-mode-map (kbd "C-c a R") #'repolens-create-new-rfc)
(define-key projectile-mode-map (kbd "C-c a t") #'repolens-run-tests)
(define-key projectile-mode-map (kbd "C-c a m") #'repolens-run-main)

(add-to-list 'projectile-globally-ignored-directories "static")
(add-to-list 'projectile-globally-ignored-directories "templates")

(setq projectile-project-root "~/sandbox/repolens")
(projectile-discover-projects-in-search-path)

(require 'org-roam)

(setq org-roam-directory (expand-file-name "docs/rfcs" (projectile-project-root)))

(defun repolens-create-rfc-nodes ()
  "Create org-roam nodes for all RFC files."
  (interactive)
  (dolist (file (directory-files org-roam-directory t "^[0-9]+-.*\\.org$"))
    (with-current-buffer (find-file-noselect file)
      (org-roam-db-update-file)
      (save-buffer))))

(defun repolens-update-rfc-links ()
  "Update links between related RFCs."
  (interactive)
  (let ((nodes (org-roam-node-list)))
    (dolist (node nodes)
      (when (string-match "RFC \\([0-9]+\\)" (org-roam-node-title node))
        (let* ((rfc-number (string-to-number (match-string 1 (org-roam-node-title node))))
               (related-rfcs (cond
                              ((member rfc-number '(0 1 3)) '(0 1 3))
                              ((member rfc-number '(2 4 18)) '(2 4 18))
                              ((member rfc-number '(9 10 11)) '(9 10 11))
                              (t nil))))
          (when related-rfcs
            (with-current-buffer (org-roam-node-file node)
              (goto-char (point-min))
              (when (search-forward "* Related RFCs" nil t)
                (forward-line 1)
                (dolist (related-rfc related-rfcs)
                  (unless (= related-rfc rfc-number)
                    (insert (format "- [[id:%s][RFC %03d]]\n"
                                    (org-roam-node-id (org-roam-node-from-title-or-alias (format "RFC %03d" related-rfc)))
                                    related-rfc))))))))))))

(repolens-create-rfc-nodes)
(repolens-update-rfc-links)

(require 'forge)

(defun repolens-create-github-issue-from-rfc ()
  "Create a GitHub issue based on the current RFC."
  (interactive)
  (let* ((title (org-get-title))
         (body (org-export-string-as (buffer-string) 'md t '(:with-toc nil)))
         (repo (forge-get-repository t)))
    (forge-create-issue repo
                        `((title . ,title)
                          (body . ,body)))))

(defun repolens-update-rfc-status-from-github ()
  "Update RFC status based on linked GitHub issue status."
  (interactive)
  (let* ((issue-number (org-entry-get nil "GITHUB_ISSUE"))
         (repo (forge-get-repository t))
         (issue (forge-get-issue repo issue-number)))
    (when issue
      (let ((new-status (pcase (oref issue state)
                          ("open" "REVIEW")
                          ("closed" "IMPLEMENTED"))))
        (org-entry-put nil "STATUS" new-status)))))

(define-key org-mode-map (kbd "C-c f i") #'repolens-create-github-issue-from-rfc)
(define-key org-mode-map (kbd "C-c f u") #'repolens-update-rfc-status-from-github)

(provide 'repolens-rfc)

(require 'org-roam)
(require 'forge)

(defun repolens-get-rfc-metadata (file)
  "Extract RFC metadata from FILE."
  (with-current-buffer (find-file-noselect file)
    (save-excursion
      (goto-char (point-min))
      (let ((case-fold-search t)
            (title (org-get-title))
            rfc-number status)
        (setq rfc-number 
              (or (when (string-match "RFC \\([0-9]+\\)" title)
                    (match-string 1 title))
                  (when (string-match "^\\([0-9]+\\)-" (file-name-nondirectory file))
                    (match-string 1 (file-name-nondirectory file)))))
        (setq status
              (or (org-entry-get (point-min) "STATUS")
                  (progn
                    (re-search-forward "^[ \t]*-[ \t]+Status:[ \t]*\\(.*\\)" nil t)
                    (match-string 1))))
        (list :title title
              :rfc-number rfc-number
              :status status
              :org-id (org-id-get-create)
              :github-issue (org-entry-get (point-min) "GITHUB_ISSUE"))))))

(defun repolens-list-rfcs-with-metadata ()
  "List all RFCs with their org-roam nodes and associated GitHub issues."
  (interactive)
  (let* ((rfc-dir (expand-file-name "docs/rfcs" (projectile-project-root)))
         (rfc-files (directory-files rfc-dir t "^[0-9]+-.*\\.org$"))
         (repo (ignore-errors (forge-get-repository t)))
         (output-buffer (get-buffer-create "*RepoLens RFCs*")))
    (with-current-buffer output-buffer
      (erase-buffer)
      (org-mode)
      (insert "* RepoLens RFCs Overview\n\n")
      (dolist (file rfc-files)
        (let* ((metadata (repolens-get-rfc-metadata file))
               (title (plist-get metadata :title))
               (rfc-number (plist-get metadata :rfc-number))
               (status (plist-get metadata :status))
               (org-id (plist-get metadata :org-id))
               (github-issue (plist-get metadata :github-issue))
               (org-roam-node (org-roam-node-from-id org-id)))
          (insert (format "** [[file:%s][RFC %s: %s]]\n" file (or rfc-number "N/A") title))
          (insert (format "   - Status: %s\n" (or status "Unknown")))
          (when org-roam-node
            (insert (format "   - org-roam: [[id:%s][%s]]\n" 
                            (org-roam-node-id org-roam-node)
                            (org-roam-node-title org-roam-node))))
          (when github-issue
            (if repo
                (let ((issue (ignore-errors (forge-get-issue repo github-issue))))
                  (if issue
                      (insert (format "   - GitHub Issue: [[https://github.com/%s/issues/%s][#%s - %s]] (%s)\n"
                                      (oref repo name)
                                      github-issue
                                      github-issue
                                      (oref issue title)
                                      (oref issue state)))
                    (insert (format "   - GitHub Issue: #%s (Not found or not synced)\n" github-issue))))
              (insert (format "   - GitHub Issue: #%s (Repository not configured in Forge)\n" github-issue))))
          (insert "\n")))
      (goto-char (point-min)))
    (switch-to-buffer output-buffer)
    (message "RFC list generated. Press q to exit the view.")))

(provide 'repolens-rfc-list)
