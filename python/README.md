# Control NanoVNA from python script

NanoVNA is able to be controlled via USB serial interface from PC. There are sample scripts in this directory.

## Preparation

    $ cd python
    $ pip3 install -r requirements.txt

## Run

### Plot reflection LOGMAG.

    $ ./nanovna.py -p

### Plot transmission LOGMAG.

    $ ./nanovna.py -p -P 1

### Plot smithchart.

    $ ./nanovna.py -s

### Capture display

    $ ./nanovna.py -C out.png

### Show usage.

    $ ./nanovna.py -h

## Using in Jupyter Notebook

The upstream notebook referenced by older versions of this README is not part
of this fork. Use `nanovna.py` as the supported sample entry point.
