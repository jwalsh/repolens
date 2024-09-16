(require 'forge)

(defun repolens-create-github-issue-from-rfc ()
  "Create a GitHub issue based on the current RFC."
  (interactive)
  (condition-case err
      (let* ((title (org-get-title))
             (body (org-export-string-as (buffer-string) 'md t '(:with-toc nil)))
             (repo (forge-get-repository t)))
        (if repo
            (forge-create-issue repo
                                `((title . ,title)
                                  (body . ,body)))
          (error "Repository not found. Please run M-x forge-add-repository first")))
    (error
     (message "Error creating issue: %s" (error-message-string err))
     (when (yes-or-no-p "Would you like to see troubleshooting steps?")
       (with-output-to-temp-buffer "*Forge Troubleshooting*"
         (princ "Forge Troubleshooting Steps:

1. Ensure you've run M-x forge-add-repository for this project.
2. Check that you have a GitHub token set up:
   - Visit https://github.com/settings/tokens
   - Generate a new token with 'repo' and 'read:org' scopes
   - Add to ~/.authinfo or ~/.authinfo.gpg:
     machine api.github.com login YOUR_GITHUB_USERNAME^forge password YOUR_TOKEN
3. Reload Forge with M-x forge-pull
4. If issues persist, check Forge documentation or seek further assistance."))))))

(defun repolens-update-rfc-status-from-github ()
  "Update RFC status based on linked GitHub issue status."
  (interactive)
  (condition-case err
      (let* ((issue-number (org-entry-get nil "GITHUB_ISSUE"))
             (repo (forge-get-repository t))
             (issue (and issue-number (forge-get-issue repo issue-number))))
        (if issue
            (let ((new-status (pcase (oref issue state)
                                ("open" "REVIEW")
                                ("closed" "IMPLEMENTED"))))
              (org-entry-put nil "STATUS" new-status))
          (error "No linked GitHub issue found. Please set the GITHUB_ISSUE property")))
    (error
     (message "Error updating RFC status: %s" (error-message-string err))
     (when (yes-or-no-p "Would you like to see troubleshooting steps?")
       (with-output-to-temp-buffer "*Forge Troubleshooting*"
         (princ "Forge Troubleshooting Steps:

1. Ensure the RFC has a GITHUB_ISSUE property set with the issue number.
2. Check that you've run M-x forge-add-repository for this project.
3. Verify your GitHub token is set up correctly in ~/.authinfo or ~/.authinfo.gpg.
4. Try running M-x forge-pull to refresh Forge data.
5. If issues persist, check Forge documentation or seek further assistance."))))))

(define-key org-mode-map (kbd "C-c f i") #'repolens-create-github-issue-from-rfc)
(define-key org-mode-map (kbd "C-c f u") #'repolens-update-rfc-status-from-github)

(provide 'repolens-rfc)
