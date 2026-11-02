pipeline {
  agent any

  stages {
    stage('Checkout') {
      steps { checkout scm }
    }

    stage('Build image') {
      steps {
        sh 'docker build -t factory-fault-tracker:${BUILD_NUMBER} -t factory-fault-tracker:latest .'
      }
    }

    stage('Test') {
      steps {
        // Placeholder: replace with real tests (e.g. pytest) later
        sh 'docker run --rm factory-fault-tracker:latest python --version'
      }
    }

    stage('Deploy') {
      steps {
        sh '''
          docker rm -f factory-fault-tracker || true
          docker run -d --name factory-fault-tracker \
            --network devops -p 8000:8000 \
            --restart unless-stopped \
            factory-fault-tracker:latest
        '''
      }
    }
  }
}
