;; Ensure org is loaded
(require 'org)

;; Ensure necessary packages are installed
(use-package projectile
  :ensure t
  :config
  (projectile-mode +1)
  :bind-keymap
  ("C-c p" . projectile-command-map))

(use-package forge
  :after magit
  :ensure t)

;; Initialize Projectile
(projectile-mode +1)

;; Define RepoLens project type
(projectile-register-project-type 'repolens '("README.md" ".git")
                                  :project-file "README.md"
                                  :compile "make build"
                                  :test "make test"
                                  :run "make run"
                                  :test-suffix "_test")

;; Set Projectile's search path
(setq projectile-project-search-path '("~/sandbox/repolens"))

;; Refresh Projectile's cache
(projectile-discover-projects-in-search-path)

;; Configure Forge
(with-eval-after-load 'magit
  (require 'forge)
  (add-to-list 'forge-alist '("github.com" "api.github.com" "github.com" forge-github-repository)))

;; Function to open RepoLens project
(defun open-repolens-project ()
  "Open the RepoLens project."
  (interactive)
  (projectile-switch-project-by-name "~/sandbox/repolens"))

;; Bind the function to a key
(global-set-key (kbd "C-c r") 'open-repolens-project)

;; Optionally, set the default directory for Emacs
(setq default-directory "~/sandbox/repolens")

;; Check org version and provide fallback if necessary
(if (fboundp 'org-element-property)
    (defalias 'repolens-org-property 'org-element-property)
  (defalias 'repolens-org-property 'org-element-get-property))

;; Projectile setup
(use-package projectile
  :ensure t
  :config
  (projectile-mode +1)
  :bind-keymap
  ("C-c p" . projectile-command-map))

;; Forge setup
(use-package forge
  :after magit
  :ensure t)

;; Initialize Projectile
(projectile-mode +1)

;; Define RepoLens project type
(projectile-register-project-type 'repolens '("README.md" ".git")
                                  :project-file "README.md"
                                  :compile "make build"
                                  :test "make test"
                                  :run "make run"
                                  :test-suffix "_test")

;; Set Projectile's search path
(setq projectile-project-search-path '("~/sandbox/repolens"))

;; Refresh Projectile's cache
(projectile-discover-projects-in-search-path)

;; Configure Forge
(with-eval-after-load 'magit
  (require 'forge)
  (add-to-list 'forge-alist '("github.com" "api.github.com" "github.com" forge-github-repository)))

;; Function to open RepoLens project
(defun open-repolens-project ()
  "Open the RepoLens project."
  (interactive)
  (projectile-switch-project-by-name "~/sandbox/repolens"))

;; Bind the function to a key
(global-set-key (kbd "C-c r") 'open-repolens-project)

;; RepoLens RFC management functions
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
      (unless (repolens-org-property :ID (org-element-at-point))
        (org-id-get-create)))))

(defun repolens-update-rfc-metadata ()
  "Update the RFC metadata, including filename and last updated date."
  (interactive)
  (let ((filename (repolens-get-rfc-filename)))
    (when filename
      (save-excursion
        (goto-char (point-min))
        (when (re-search-forward "^\\* \\(DRAFT \\)?Metadata$" nil t)
          (let ((metadata-id (repolens-org-property :ID (org-element-at-point))))
            (when metadata-id
              (org-set-property "LAST_UPDATED" (format-time-string "[%Y-%m-%d %a]"))
              (unless (repolens-org-property :FILENAME (org-element-at-point))
                (org-set-property "FILENAME" filename)))))))))

(defun repolens-initialize-rfc ()
  "Initialize or update RFC metadata."
  (when (repolens-get-rfc-filename)
    (repolens-ensure-rfc-metadata-id)
    (repolens-update-rfc-metadata)))

;; Hooks
(add-hook 'find-file-hook 'repolens-initialize-rfc)
(add-hook 'before-save-hook 'repolens-update-rfc-metadata)

;; Provide the feature
(provide 'repolens-setup)
