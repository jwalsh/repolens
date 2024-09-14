document.addEventListener('DOMContentLoaded', () => {
    const packageForm = document.getElementById('package-form');
    const analyzeForm = document.getElementById('analyze-form');
    const quickAnalysisForm = document.getElementById('quick-analysis-form');
    const resultsDiv = document.getElementById('results');
    const loginButton = document.getElementById('login-button');

    // Fetch the RepoLens repository ID
    fetch('/api/repository/repolens')
        .then(response => response.json())
        .then(data => {
            if (data.id) {
                document.getElementById('repo-id').value = data.id;
            }
        })
        .catch(error => console.error('Error fetching RepoLens repository ID:', error));

    function showLoading(message) {
        resultsDiv.innerHTML = `<p>${message} Please wait...</p><div class="loading"></div>`;
    }

    function showError(message) {
        resultsDiv.innerHTML = `<p class="error">Error: ${message}</p>`;
    }

    function displayResults(data, analysisId) {
        const downloadButton = `<button onclick="downloadRepositoryContent(${data.repository_id})">Download Repository Content</button>`;
        resultsDiv.innerHTML = `
            <h3>Analysis Results:</h3>
            <p>Repository: ${data.repository_name} (ID: ${data.repository_id})</p>
            <p>Analysis ID: <strong>${analysisId}</strong></p>
            <pre>${JSON.stringify(data.result, null, 2)}</pre>
            ${downloadButton}
        `;
    }

    packageForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const repoUrl = document.getElementById('repo-url').value;
        
        showLoading('Packaging repository...');
        
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
                resultsDiv.innerHTML = `
                    <p>Repository packaged successfully!</p>
                    <p>Repository: ${data.repo_name} (ID: ${data.repo_id})</p>
                    <p>Use this ID for analysis.</p>
                `;
            } else {
                showError(data.error);
            }
        } catch (error) {
            showError(error.message);
        }
    });

    analyzeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const repoId = document.getElementById('repo-id').value;
        const analysisType = document.getElementById('analysis-type').value;
        
        showLoading('Analyzing repository...');
        
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
                const analysisId = data.analysis_id;
                const analysisResponse = await fetch(`/api/analysis/${analysisId}`);
                const analysisData = await analysisResponse.json();
                
                displayResults(analysisData, analysisId);
            } else {
                showError(data.error);
            }
        } catch (error) {
            showError(error.message);
        }
    });

    quickAnalysisForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const repoUrl = document.getElementById('quick-repo-url').value;
        
        showLoading('Packaging and analyzing repository...');
        
        try {
            const packageResponse = await fetch('/api/package', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ repo_url: repoUrl }),
            });
            
            const packageData = await packageResponse.json();
            
            if (packageResponse.ok) {
                const repoId = packageData.repo_id;
                const analysisType = 'file_count'; // Default analysis type
                
                const analyzeResponse = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ repo_id: repoId, analysis_type: analysisType }),
                });
                
                const analyzeData = await analyzeResponse.json();
                
                if (analyzeResponse.ok) {
                    const analysisId = analyzeData.analysis_id;
                    const analysisResponse = await fetch(`/api/analysis/${analysisId}`);
                    const analysisData = await analysisResponse.json();
                    
                    displayResults(analysisData, analysisId);
                } else {
                    showError(analyzeData.error);
                }
            } else {
                showError(packageData.error);
            }
        } catch (error) {
            showError(error.message);
        }
    });

    loginButton.addEventListener('click', (e) => {
        e.preventDefault();
        // Placeholder for future GitHub authentication
        alert('GitHub authentication coming soon!');
    });
});

function downloadRepositoryContent(repoId) {
    window.location.href = `/api/download/${repoId}`;
}
