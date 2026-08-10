package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"io"
	"log"
	"math/big"
	"os"
	"time"
)

func GenerateTLSCerts(certPath string) (*bytes.Buffer, error) {
	var (
		webhookNamespace         = os.Getenv("WEBHOOK_NAMESPACE")
		webhookService           = os.Getenv("WEBHOOK_SERVICE")
		organization             = os.Getenv("ORGANIZATION")
		caPEMFilename            = certPath + "/ca.pem"
		serverCertPEMFilename    = certPath + "/cert.pem"
		serverPrivKeyPEMFilename = certPath + "/key.pem"
		existingFilesFound       = false
		existingFilesCount       = 0
	)

	if _, err := os.Stat(caPEMFilename); err == nil {
		fmt.Printf("Using existing file: " + caPEMFilename + "\n")
		existingFilesFound = true
		existingFilesCount += 1
	} else {
		fmt.Printf("will create " + caPEMFilename + "\n")
	}

	if _, err := os.Stat(serverCertPEMFilename); err == nil {
		fmt.Printf("Using existing file: " + serverCertPEMFilename + "\n")
		existingFilesFound = true
		existingFilesCount += 1
	} else {
		fmt.Printf("will create " + serverCertPEMFilename + "\n")
	}

	if _, err := os.Stat(serverPrivKeyPEMFilename); err == nil {
		fmt.Printf("Using existing file: " + serverPrivKeyPEMFilename + "\n")
		existingFilesFound = true
		existingFilesCount += 1
	} else {
		fmt.Printf("will create " + serverPrivKeyPEMFilename + "\n")
	}

	if existingFilesFound && existingFilesCount == 3 {
		// Read in ca from file.
		caPEM := ReadFile(caPEMFilename)
		return caPEM, nil
	} else if existingFilesFound {
		log.Println("Existing cert files found, but not all.  Delete all and rerun.")
		return nil, nil
	} else {

		ca := &x509.Certificate{
			SerialNumber: big.NewInt(2023),
			Subject: pkix.Name{
				Organization: []string{organization},
			},
			NotBefore:             time.Now(),
			NotAfter:              time.Now().AddDate(1, 0, 0),
			IsCA:                  true,
			ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
			KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
			BasicConstraintsValid: true,
		}

		// CA private key
		caPrivKey, err := rsa.GenerateKey(rand.Reader, 4096)
		if err != nil {
			log.Println("Error: generating private key ", err)
			return nil, err
		}

		// Self signed CA certificate based on template above
		caBytes, err := x509.CreateCertificate(rand.Reader, ca, ca, &caPrivKey.PublicKey, caPrivKey)
		if err != nil {
			log.Println("Error: generating self signed certificate ", err)
			return nil, err
		}

		// PEM encode CA certificate
		caPEM := new(bytes.Buffer)
		_ = pem.Encode(caPEM, &pem.Block{
			Type:  "CERTIFICATE",
			Bytes: caBytes,
		})

		// Very important to mirror the name of the service
		// [name of service].[namespace].svc for dns
		dnsNames := []string{webhookService,
			webhookService + "." + webhookNamespace, webhookService + "." + webhookNamespace + ".svc"}

		// server cert config
		cert := &x509.Certificate{
			DNSNames:     dnsNames,
			SerialNumber: big.NewInt(1658),
			Subject: pkix.Name{
				CommonName:   webhookService,
				Organization: []string{organization},
			},
			NotBefore:    time.Now(),
			NotAfter:     time.Now().AddDate(1, 0, 0),
			SubjectKeyId: []byte{1, 2, 3, 4, 6},
			ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
			KeyUsage:     x509.KeyUsageDigitalSignature,
		}

		// server private key
		serverPrivKey, err := rsa.GenerateKey(rand.Reader, 4096)
		if err != nil {
			log.Println("Error: generating server priv key ", err)
			return nil, err
		}
		// sign the server certificate, note parent is ca created at the beginning
		serverCertBytes, err := x509.CreateCertificate(rand.Reader, cert, ca, &serverPrivKey.PublicKey, caPrivKey)
		if err != nil {
			log.Println("Error: creating server cert ", err)
			return nil, err
		}
		// PEM encode the server cert and key
		serverCertPEM := new(bytes.Buffer)
		_ = pem.Encode(serverCertPEM, &pem.Block{
			Type:  "CERTIFICATE",
			Bytes: serverCertBytes,
		})

		serverPrivKeyPEM := new(bytes.Buffer)
		_ = pem.Encode(serverPrivKeyPEM, &pem.Block{
			Type:  "RSA PRIVATE KEY",
			Bytes: x509.MarshalPKCS1PrivateKey(serverPrivKey),
		})

		err = os.MkdirAll(certPath, 0755)
		if err != nil {
			log.Println("Error: Creating Directory ", err)
			return nil, err
		}

		err = WriteFile(caPEMFilename, caPEM)
		if err != nil {
			log.Println("Error: Writing "+caPEMFilename, err)
			return nil, err
		}
		err = WriteFile(serverCertPEMFilename, serverCertPEM)
		if err != nil {
			log.Println("Error: Writing cert.pem ", err)
			return nil, err
		}
		err = WriteFile(serverPrivKeyPEMFilename, serverPrivKeyPEM)
		if err != nil {
			log.Println("Error: Writing key.pem ", err)
			return nil, err

		}
		return caPEM, nil
	}
}

// WriteFile writes data in the file at the given path
func WriteFile(filepath string, sCert *bytes.Buffer) error {
	f, err := os.Create(filepath)
	if err != nil {
		return err
	}
	defer f.Close()

	_, err = f.Write(sCert.Bytes())
	if err != nil {
		return err
	}
	return nil
}

func ReadFile(fileName string) *bytes.Buffer {
	buf := new(bytes.Buffer)
	file, err := os.Open(fileName)
	if err != nil {
		fmt.Println(err)
		return nil
	}
	defer file.Close()

	// Get the file size
	stat, err := file.Stat()
	if err != nil {
		fmt.Println(err)
		return nil
	}

	// Read the file into a byte slice
	bs := make([]byte, stat.Size())
	_, err = bufio.NewReader(file).Read(bs)
	if err != nil && err != io.EOF {
		fmt.Println(err)
		return nil
	}
	// fmt.Println(bs)
	buf.Write(bs)
	return buf
}
