/**
 * Dashboard functionality for LoadHarness.
 * Handles tab switching, slider controls, and client-side job tracking.
 */
(function() {
    'use strict';

    // ========================================================================
    // Tab Switching
    // ========================================================================
    document.querySelectorAll('.tab-btn').forEach(function(button) {
        button.addEventListener('click', function() {
            var tabName = button.dataset.tab;

            // Update button styles
            document.querySelectorAll('.tab-btn').forEach(function(btn) {
                btn.classList.remove('border-primary-500', 'text-primary-600');
                btn.classList.add('border-transparent', 'text-gray-500');
            });
            button.classList.remove('border-transparent', 'text-gray-500');
            button.classList.add('border-primary-500', 'text-primary-600');

            // Show/hide tab content
            document.querySelectorAll('.tab-content').forEach(function(content) {
                content.classList.add('hidden');
            });
            document.getElementById('tab-' + tabName).classList.remove('hidden');

            // Switch right panel based on tab
            var activeJobsPanel = document.getElementById('active-jobs-panel');
            var podMonitorPanel = document.getElementById('pod-monitor-panel');

            if (tabName === 'cluster') {
                // Show Pod Monitor for Cluster Load tab
                activeJobsPanel.classList.add('hidden');
                podMonitorPanel.classList.remove('hidden');
            } else {
                // Show Active Jobs for CPU Load and Memory Load tabs
                activeJobsPanel.classList.remove('hidden');
                podMonitorPanel.classList.add('hidden');
            }
        });
    });

    // ========================================================================
    // Utility Functions
    // ========================================================================

    // Convert intensity value (1-10) to descriptive label
    function getIntensityLabel(value) {
        var v = parseInt(value, 10);
        if (v <= 3) return 'Low';
        if (v <= 6) return 'Medium';
        if (v <= 8) return 'High';
        return 'Extreme';
    }

    // Format duration in seconds to human readable
    function formatDuration(seconds) {
        var s = parseInt(seconds, 10);
        if (s < 60) return s + 's';
        if (s < 120) return '1 min';
        if (s % 60 === 0) return Math.floor(s / 60) + ' min';
        return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
    }

    // Format iterations to human readable (100K, 1M, etc)
    function formatIterations(value) {
        var v = parseInt(value, 10);
        if (v >= 1000000) return (v / 1000000) + 'M';
        return (v / 1000) + 'K';
    }

    // Make formatDuration available globally for job rendering
    window.formatDuration = formatDuration;

    // ========================================================================
    // Slider Value Updates
    // ========================================================================

    var cpuCoresSlider = document.getElementById('cpu-cores');
    var cpuCoresValue = document.getElementById('cpu-cores-value');
    if (cpuCoresSlider && cpuCoresValue) {
        cpuCoresSlider.addEventListener('input', function() {
            cpuCoresValue.textContent = cpuCoresSlider.value;
        });
    }

    var cpuDurationSlider = document.getElementById('cpu-duration');
    var cpuDurationValue = document.getElementById('cpu-duration-value');
    if (cpuDurationSlider && cpuDurationValue) {
        cpuDurationSlider.addEventListener('input', function() {
            cpuDurationValue.textContent = formatDuration(cpuDurationSlider.value);
        });
    }

    var cpuIntensitySlider = document.getElementById('cpu-intensity');
    var cpuIntensityLabel = document.getElementById('cpu-intensity-label');
    if (cpuIntensitySlider && cpuIntensityLabel) {
        cpuIntensitySlider.addEventListener('input', function() {
            cpuIntensityLabel.textContent = getIntensityLabel(cpuIntensitySlider.value);
        });
    }

    var memorySizeSlider = document.getElementById('memory-size');
    var memorySizeValue = document.getElementById('memory-size-value');
    if (memorySizeSlider && memorySizeValue) {
        memorySizeSlider.addEventListener('input', function() {
            memorySizeValue.textContent = memorySizeSlider.value;
        });
    }

    var memoryDurationSlider = document.getElementById('memory-duration');
    var memoryDurationValue = document.getElementById('memory-duration-value');
    if (memoryDurationSlider && memoryDurationValue) {
        memoryDurationSlider.addEventListener('input', function() {
            memoryDurationValue.textContent = formatDuration(memoryDurationSlider.value);
        });
    }

    var clusterConcurrencySlider = document.getElementById('cluster-concurrency');
    var clusterConcurrencyValue = document.getElementById('cluster-concurrency-value');
    if (clusterConcurrencySlider && clusterConcurrencyValue) {
        clusterConcurrencySlider.addEventListener('input', function() {
            clusterConcurrencyValue.textContent = clusterConcurrencySlider.value;
        });
    }

    var clusterIterationsSlider = document.getElementById('cluster-iterations');
    var clusterIterationsValue = document.getElementById('cluster-iterations-value');
    if (clusterIterationsSlider && clusterIterationsValue) {
        clusterIterationsSlider.addEventListener('input', function() {
            clusterIterationsValue.textContent = formatIterations(clusterIterationsSlider.value);
        });
    }

    // ========================================================================
    // Client-side Job Tracking
    // ========================================================================
    // Jobs are tracked in the browser to avoid multi-pod polling issues.
    // When HPA scales pods, each pod has its own job state, so polling
    // random pods would show inconsistent results.
    // Jobs are persisted to localStorage to survive page refreshes.

    var JOBS_STORAGE_KEY = 'loadharness_active_jobs';
    var activeJobs = new Map();

    function saveJobsToStorage() {
        var jobsArray = Array.from(activeJobs.entries());
        localStorage.setItem(JOBS_STORAGE_KEY, JSON.stringify(jobsArray));
    }

    function loadJobsFromStorage() {
        try {
            var stored = localStorage.getItem(JOBS_STORAGE_KEY);
            if (stored) {
                var jobsArray = JSON.parse(stored);
                jobsArray.forEach(function(entry) {
                    var jobId = entry[0];
                    var job = entry[1];
                    // Only restore jobs that haven't expired (completed + 30s buffer)
                    if (job.endTime > Date.now() - 30000) {
                        activeJobs.set(jobId, job);
                    }
                });
            }
        } catch (e) {
            console.warn('Failed to load jobs from storage:', e);
        }
    }

    function renderJobs() {
        var jobsList = document.getElementById('jobs-list');
        var jobsEmpty = document.getElementById('jobs-empty');

        if (!jobsList || !jobsEmpty) return;

        if (activeJobs.size === 0) {
            jobsList.innerHTML = '';
            jobsEmpty.classList.remove('hidden');
            return;
        }

        jobsEmpty.classList.add('hidden');

        var html = '<div class="space-y-3">';
        activeJobs.forEach(function(job, jobId) {
            var remaining = Math.max(0, job.endTime - Date.now());
            var remainingSec = Math.ceil(remaining / 1000);
            var isRunning = remaining > 0;
            var isCpuJob = job.type === 'cpu';

            if (isRunning) {
                html += '<div class="p-3 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg">' +
                    '<div class="flex items-center justify-between">' +
                        '<div class="flex items-center gap-2">' +
                            '<span class="relative flex h-3 w-3">' +
                                '<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>' +
                                '<span class="relative inline-flex rounded-full h-3 w-3 bg-blue-500"></span>' +
                            '</span>' +
                            '<span class="text-sm font-medium text-blue-800 dark:text-blue-200">' + (isCpuJob ? 'CPU' : 'Memory') + '</span>' +
                        '</div>' +
                        '<span class="text-xs text-blue-600 dark:text-blue-400 font-mono">' + jobId.slice(-12) + '</span>' +
                    '</div>' +
                    '<div class="mt-2 grid grid-cols-2 gap-2 text-xs text-blue-700 dark:text-blue-300">' +
                        (isCpuJob ?
                            '<div><span class="text-blue-500 dark:text-blue-400">Cores:</span> <span class="font-medium">' + job.cores + '/' + job.cores + '</span></div>' +
                            '<div><span class="text-blue-500 dark:text-blue-400">Intensity:</span> <span class="font-medium">' + job.intensity + '/10</span></div>'
                        :
                            '<div><span class="text-blue-500 dark:text-blue-400">Size:</span> <span class="font-medium">' + job.size_mb + ' MB</span></div>' +
                            '<div><span class="text-blue-500 dark:text-blue-400">Allocated:</span> <span class="font-medium">Holding</span></div>'
                        ) +
                        '<div><span class="text-blue-500 dark:text-blue-400">Remaining:</span> <span class="font-medium">' + formatDuration(remainingSec) + '</span></div>' +
                        '<div><span class="text-blue-500 dark:text-blue-400">Started:</span> <span class="font-medium">' + job.startedAt + '</span></div>' +
                    '</div>' +
                '</div>';
            } else {
                html += '<div class="p-3 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg">' +
                    '<div class="flex items-center justify-between">' +
                        '<div class="flex items-center gap-2">' +
                            '<svg class="w-4 h-4 text-green-500" fill="currentColor" viewBox="0 0 20 20">' +
                                '<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />' +
                            '</svg>' +
                            '<span class="text-sm font-medium text-green-800 dark:text-green-200">' + (isCpuJob ? 'CPU' : 'Memory') + ' Done</span>' +
                        '</div>' +
                        '<span class="text-xs text-green-600 dark:text-green-400 font-mono">' + jobId.slice(-12) + '</span>' +
                    '</div>' +
                    '<div class="mt-1 text-xs text-green-600 dark:text-green-400">' +
                        (isCpuJob ? job.cores + ' core(s), ' + job.duration + 's' : job.size_mb + ' MB, ' + job.duration + 's') +
                    '</div>' +
                '</div>';
            }
        });
        html += '</div>';
        jobsList.innerHTML = html;
    }

    function addCpuJob(jobData) {
        var now = Date.now();
        var job = {
            type: 'cpu',
            jobId: jobData.job_id,
            cores: jobData.cores,
            duration: jobData.duration_seconds,
            intensity: jobData.intensity,
            startedAt: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            endTime: now + (jobData.duration_seconds * 1000)
        };
        activeJobs.set(job.jobId, job);
        saveJobsToStorage();
        renderJobs();
    }

    function addMemoryJob(jobData) {
        var now = Date.now();
        var job = {
            type: 'memory',
            jobId: jobData.job_id,
            size_mb: jobData.size_mb,
            duration: jobData.duration_seconds,
            startedAt: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            endTime: now + (jobData.duration_seconds * 1000)
        };
        activeJobs.set(job.jobId, job);
        saveJobsToStorage();
        renderJobs();
    }

    // Clean up completed jobs after 30 seconds
    function cleanupCompletedJobs() {
        var now = Date.now();
        var deleted = false;
        activeJobs.forEach(function(job, jobId) {
            // Remove jobs that completed more than 30 seconds ago
            if (job.endTime < now - 30000) {
                activeJobs.delete(jobId);
                deleted = true;
            }
        });
        if (deleted) {
            saveJobsToStorage();
        }
        renderJobs();
    }

    // Listen for successful load responses via HTMX
    document.body.addEventListener('htmx:afterSwap', function(event) {
        if (event.detail.target.id === 'result') {
            var resultHtml = event.detail.target.innerHTML;

            // Check if it's a CPU Load success response by looking for job_id
            var cpuJobIdMatch = resultHtml.match(/job_(\d+)/);
            if (cpuJobIdMatch && resultHtml.includes('CPU Load')) {
                var coresMatch = resultHtml.match(/>Cores<\/dt>\s*<dd[^>]*>\s*(\d+)\s*<\/dd>/);
                var durationMatch = resultHtml.match(/>Duration<\/dt>\s*<dd[^>]*>\s*(\d+)s\s*<\/dd>/);
                var intensityMatch = resultHtml.match(/>Intensity<\/dt>\s*<dd[^>]*>\s*(\d+)\s*\/\s*10\s*<\/dd>/);

                if (coresMatch && durationMatch && intensityMatch) {
                    addCpuJob({
                        job_id: 'job_' + cpuJobIdMatch[1],
                        cores: parseInt(coresMatch[1], 10),
                        duration_seconds: parseInt(durationMatch[1], 10),
                        intensity: parseInt(intensityMatch[1], 10)
                    });
                }
            }

            // Check if it's a Memory Load success response by looking for mem_id
            var memJobIdMatch = resultHtml.match(/mem_(\d+)/);
            if (memJobIdMatch && resultHtml.includes('Memory Load')) {
                var sizeMatch = resultHtml.match(/>Size<\/dt>\s*<dd[^>]*>\s*(\d+)\s*MB\s*<\/dd>/);
                var memDurationMatch = resultHtml.match(/>Duration<\/dt>\s*<dd[^>]*>\s*(\d+)s\s*<\/dd>/);

                if (sizeMatch && memDurationMatch) {
                    addMemoryJob({
                        job_id: 'mem_' + memJobIdMatch[1],
                        size_mb: parseInt(sizeMatch[1], 10),
                        duration_seconds: parseInt(memDurationMatch[1], 10)
                    });
                }
            }
        }
    });

    // ========================================================================
    // Initialization
    // ========================================================================
    loadJobsFromStorage();
    renderJobs();

    // Update job display every second (for countdown)
    setInterval(renderJobs, 1000);
    // Cleanup old completed jobs every 10 seconds
    setInterval(cleanupCompletedJobs, 10000);
})();
