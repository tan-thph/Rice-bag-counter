new Vue({
    el: '#app',
    data: {
        currentPage: 'home',
        cameras: [],
        activeJobs: {},
        jobResults: [],
        liveJob: {
            job_type: 'live',
            camera: '',
            customer_name: '',
            truck_number: '',
            commodity: '',
            weight_per_unit: 0,
            order_number: '',
            note: '',
            detection_line_orientation: 'vertical',
            detection_line_position: 0.5
        },
        videoJob: {
            job_type: 'video',
            customer_name: '',
            truck_number: '',
            commodity: '',
            weight_per_unit: 0,
            order_number: '',
            note: '',
            detection_line_orientation: 'vertical',
            detection_line_position: 0.5
        },
        uploadProgress: 0,
        selectedFile: null
    },
    mounted() {
        this.loadInitialData();
    },
    methods: {
        loadInitialData() {
            const initialData = JSON.parse(document.getElementById('initial-data').textContent);
            this.cameras = initialData.cameras;
            this.activeJobs = initialData.activeJobs;
            this.jobResults = initialData.jobResults;
        },
        createLiveJob() {
            this.createJob(this.liveJob);
        },
        createVideoJob() {
            if (this.selectedFile) {
                this.uploadVideo().then(response => {
                    this.videoJob.video_path = response.filename;
                    this.createJob(this.videoJob);
                });
            }
        },
        createJob(job) {
            fetch('/jobs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(job),
            })
            .then(response => response.json())
            .then(data => {
                console.log('Job created:', data);
                this.currentPage = 'results';
            })
            .catch((error) => {
                console.error('Error:', error);
            });
        },
        handleFileUpload(event) {
            this.selectedFile = event.target.files[0];
        },
        uploadVideo() {
            return new Promise((resolve, reject) => {
                const formData = new FormData();
                formData.append('file', this.selectedFile);
    
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/upload_video', true);
    
                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable) {
                        this.uploadProgress = (event.loaded / event.total) * 100;
                    }
                };
    
                xhr.onload = () => {
                    if (xhr.status === 200) {
                        const response = JSON.parse(xhr.responseText);
                        resolve(response);
                    } else {
                        reject(new Error('Upload failed'));
                    }
                };
    
                xhr.onerror = () => {
                    reject(new Error('Network error'));
                };
    
                xhr.send(formData);
            });
        },
        stopJob(jobId) {
            fetch(`/stop_job/${jobId}`, {
                method: 'POST',
            })
            .then(response => response.json())
            .then(data => {
                console.log('Job stopped:', data);
                delete this.activeJobs[jobId];
            })
            .catch((error) => {
                console.error('Error:', error);
            });
        },
        updateJobResults() {
            fetch('/job_results')
            .then(response => response.json())
            .then(data => {
                this.jobResults = data;
            })
            .catch((error) => {
                console.error('Error:', error);
            });
        }
    }
});