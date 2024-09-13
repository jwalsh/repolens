document.addEventListener('DOMContentLoaded', () => {
    const packageForm = document.getElementById('package-form');
    const analyzeForm = document.getElementById('analyze-form');
    const resultsDiv = document.getElementById('results');

    packageForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const repoUrl = document.getElementById('repo-url').value;
        
        try {
            const response = await fetch('/api/package', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ repo_url: repoUrl }),
            });
            
            const data = await response.json();
            
            if (response.ok) {
                resultsDiv.innerHTML = `<p>Repository packaged successfully. Repo ID: ${data.repo_id}</p>`;
            } else {
                resultsDiv.innerHTML = `<p>Error: ${data.error}</p>`;
            }
        } catch (error) {
            resultsDiv.innerHTML = `<p>Error: ${error.message}</p>`;
        }
    });

    analyzeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const repoId = document.getElementById('repo-id').value;
        const analysisType = document.getElementById('analysis-type').value;
        
        try {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ repo_id: repoId, analysis_type: analysisType }),
            });
            
            const data = await response.json();
            
            if (response.ok) {
                resultsDiv.innerHTML = `<p>Analysis completed successfully. Analysis ID: ${data.analysis_id}</p>`;
            } else {
                resultsDiv.innerHTML = `<p>Error: ${data.error}</p>`;
            }
        } catch (error) {
            resultsDiv.innerHTML = `<p>Error: ${error.message}</p>`;
        }
    });
});
