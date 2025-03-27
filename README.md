## Code-env config after installation:
plugin_meme-tools_managed > Containerized execution > Advanced container settings

```docker
# Install system dependencies, including Perl
RUN yum groupinstall -y "Development Tools" && \
    yum install -y \
    wget \
    zlib-devel \
    libxml2-devel \
    expat-devel \
    libxslt-devel \
    openmpi-devel \
    bzip2 \
    gcc-c++ \
    which \
    perl \
    && yum clean all


# Update the system and install system libraries and development tools
RUN dnf install -y  libxslt libxslt-devel \
    perl perl-core perl-CPAN gcc make \
    libxml2-devel expat-devel perl-App-cpanminus \
    && dnf clean all

# Set environment variable to automatically answer 'yes' in CPAN
ENV PERL_MM_USE_DEFAULT=1

# Install required Perl modules using cpan

# Create a dummy /etc/fstab file
RUN echo "# Dummy fstab for container" > /etc/fstab

# Install required Perl modules
RUN cpan Sys::Info::Driver::Linux::OS
RUN cpan Sys::Info::Driver::Linux::Device
RUN cpan Sys::Info

RUN cpan XML::NamespaceSupport XML::SAX::DocumentLocator  XML::SAX  XML::SAX::Exception XML::SAX::Base \
    HTML::PullParser HTML::Template HTML::TreeBuilder JSON Sys::Info \
    Log::Log4perl Math::CDF XML::Compile::SOAP11 XML::Compile::WSDL11 XML::Compile::Transport::SOAPHTTP

RUN PERL_MM_USE_DEFAULT=1 cpan XML::Simple

# Set environment variables
ENV MEME_VERSION=5.5.7
ENV MEME_DIR=/usr/local/meme


RUN wget https://meme-suite.org/meme/meme-software/${MEME_VERSION}/meme-${MEME_VERSION}.tar.gz && \
    tar zxf meme-${MEME_VERSION}.tar.gz && \
    cd meme-${MEME_VERSION} && \
    ./configure --prefix=$MEME_DIR --enable-build-libxml2 --enable-build-libxslt --with-python=/usr/local/bin/python3.10 && \
    make && \
    make test &&\
    make install || true


# Add MEME Suite to PATH
ENV PATH="${MEME_DIR}/bin:${PATH}"


# Clean up
RUN rm -rf ./meme-${MEME_VERSION}.tar.gz ./meme-${MEME_VERSION}



# Verify installation
RUN streme --version
RUN fimo --version
```
